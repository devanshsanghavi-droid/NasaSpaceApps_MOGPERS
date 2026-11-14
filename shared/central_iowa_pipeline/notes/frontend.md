# Module: frontend

Static web app in `web/`. No build step. CDN libraries are pinned: MapLibre GL JS 4.7.1 (unpkg) and Chart.js 4.4.4 (jsdelivr). The basemaps are OpenFreeMap `positron` (light) and `dark` (dark mode). Neither needs a key; both were checked to load.

## Run

```
.venv/bin/python pipeline/frontend_mockdata.py            # (re)writes web/mock/*.json, all marked MOCK
.venv/bin/python pipeline/frontend_counties.py            # copies REAL data/counties.geojson -> web/data/counties.geojson
.venv/bin/python -m http.server 8765 --directory web       # then open http://localhost:8765/
```
To deep-link a field, put its id in the hash, e.g. `http://localhost:8765/#f23608`. **That id is the knoll hero only in the mock data.** It is a real `is_field` row in `data/fields.parquet` (Story County), but once the real `hero_fields.json` is exported, the heroes are whatever the exporter picks. Any `is_field` id deep-links to its field panel; only hero ids get twins.

## Data flow

1. `js/data.js#loadAll()` loads each contract file from `web/data/<file>` first and falls back to `web/mock/<file>`. It first reads the directory listing that `http.server` serves for `data/`, so files that have not been exported are skipped without 404 noise. On hosts with no listing, it probes each file directly.
2. Every file records where it came from (`data` / `mock` / `missing`). A file in `web/data/` that still has a top-level `"mock": true` counts as mock.
3. If any file is mock or missing, a sticky **MOCK DATA** banner appears. It says either "every number is synthetic" or names the placeholder files. The Data section also has a table showing each file's source. When a real file is dropped into `web/data/`, it wins on the next reload (I tested this with a temporary file, then removed it).
4. All state lives in `app.js`: the loaded data, the selected field, the year and scenario, the preference weights and answers. Rendering is plain DOM templating.

Files loaded: `meta, fields_index, field_types, effects, hero_fields, hindcast, climate, policy, signpost, badge_calibration` (`.json`) plus **`counties.geojson`**. The web contract has no counties file, so the frontend module provides it itself: `pipeline/frontend_counties.py` copies the real `data/counties.geojson` (context module, US Census 2023 cartographic boundaries, 14 counties, properties `name`, `fips`, `state_abbr`, `frac_in_tile`) to `web/data/counties.geojson`. **That file is already in place**, so the map draws real county outlines. If it goes missing, the app falls back to approximate mock rectangles. County outlines carry no estimates, so `counties` never triggers the MOCK banner on its own: once every contract file is real, the banner goes away.

`web/data/README.txt` keeps the directory present (an empty directory can be dropped by a copy or VCS), so the directory-listing probe never 404s.

## Component map

| File | What it renders / does |
|---|---|
| `index.html` | Shell: top bar, mock banner, workbench (map + panel), Hindcast, County and Data sections, footer |
| `styles.css` | Tokens (ink / ground / one indigo accent + dataviz palette), dark mode via `prefers-color-scheme` and `[data-theme]`, layouts for 860 px and 480 px |
| `app.js` | Loads data, builds state, sets up map and legend, handles selection and `#hash`, runs the preference workflow (Bradley-Terry), mounts the sections |
| `js/map.js` `FieldMap` | Demo moment 1: county outlines and labels, every field sample as a circle coloured by **best strategy / evidence badge / field type**, hero markers and labels, hover popup, click to select, emphasis on same-type fields. Demo moment 3: twin rings plus dashed hero-to-twin lines, fitted to view |
| `js/map.js` `AnalogMap` | Demo moment 5: inset map of climate analogs. Created once, then moved into the panel |
| `js/panel.js` | Demo moment 2: field panel (type in plain words, county, crop-sequence chips, story, Listen / twins / zoom buttons), season ribbon (bare_frac, erosivity, heat_risk), "Meet your twins" synthetic-control chart with pre/post gap stats computed from the JSON, the "Drag to 2045" control, preference cards, strategy cards S0..S3, and the signpost card (demo moment 6) |
| `js/charts.js` | Chart.js synthetic control (actual, counterfactual dashed, 90% band, switch-year marker) and the CMIP6 heat trajectory (linear year axis: historical 1995-2014 per year, dotted interpolation, both SSPs 2035-2055, numeric marker for the selected year) |
| `js/model.js` | Outcome metadata (sign, units), utility, ranking, Bradley-Terry weight fit, climate transport |
| `js/sections.js` | Demo moment 4: "Press hindcast" (metric grid plus per-type ranking table with a staggered reveal). Demo moment 7: County policy tree (rules, recommended strategy, n, value per $1, value vs uniform). Demo moment 10: data sources (NASA tag) and caveats |
| `js/voice.js` | Demo moment 9: "Listen" via the Web Speech API. The summary is built only from JSON values, prefixed with a mock warning when needed, and ends with the agronomist disclaimer |
| `js/util.js` | Escaping, number formatting (real minus sign), CSS-token colours, the tooltip system (`data-tip`, hover and focus) |

### Strategy cards (from `effects.json`)
- S0 is always first and is the reference. S1..S3 are ranked by utility. The rank label says "by default balance" until preferences have been answered, then "for your priorities".
- Every card shows: why suggested; the evidence badge (signal-bars glyph + word; tooltip built from `badge_calibration`, e.g. "strong-badged estimates were wrong 6% of the time (n=420); 90% intervals contained the truth 91%"); twin fields, trials, quasi-experiment, Gamma and overlap (each with a tooltip); and an interval bar per outcome on an axis shared across the cards of that type. **Measured outcomes are solid, modelled ones (`measured:false`) striped, and beyond-evidence ones hatched and dashed.** Each bar also gets a plain-words verdict: "likely better" / "likely worse" / "could go either way", computed from the sign of lo/hi and which direction is good for that outcome.
- A key-value grid lists information gaps, risks needing local review, "When it fails" (failure_box), the signpost (labelled as agronomic guidance), the next best step and who pays. An estimator cross-check table (DR-learner / DiD / forest) sits behind a `<details>`.

### Drag to 2045 (climate transport)
`climate[ssp].est/lo/hi` in `effects.json` is read as the **yield_pct** effect for the 2035-2055 window. For a slider year y, `f = clamp((H(y) - H(2025)) / (h45 - H(2025)), 0, 1)`, where h45 is the mean of the scenario's raw `hdd30` over 2035-2055. The real climate pipeline (`pipeline/context_climate.py`) produces SSP years **2035-2055 only** plus historical 1995-2014, so H is defined piecewise (`model.js#heatPath`):
- inside the scenario's own years: the 11-year running mean of `hdd30` (truncated window at the ends);
- before them (2025-2034): a straight line from an anchor to (2045, h45). The anchor is the mean of `historical.hdd30` placed at the mean of `historical.years` (2004.5), or an optional `climate.recent = {year, hdd30}` if an exporter adds one.

So 2025-2034 moves linearly (5% per year) and from 2035 follows the CMIP6 path. The note under the slider names which method applied. With the real NEX-GDDP-CMIP6 multi-model means (`data/climate_future.json`: historical 80.2, SSP2-4.5 179.9, SSP5-8.5 183.4 degC-days), f is 0.05 / 0.25 / 0.45 at 2026 / 2030 / 2034. At 2035 it is 0.35 under SSP2-4.5 and 0.64 under SSP5-8.5; at 2040, 0.60 and 0.86; and 1.00 from 2045. The small dip at 2035 under SSP2-4.5 is real model variability (the truncated 2035-2040 mean is cooler than the 21-year mean). It is not smoothed away. If there is no hdd30 series, f falls back to linear in time.

The heat chart (`charts.js#climateChart`) uses a **linear year axis** with `{x, y}` points: historical per year (1995-2014), a dotted straight-line interpolation from the end of the historical years to the first scenario year (the same line the transport uses), and both SSPs as 11-year running means over 2035-2055. The selected scenario is drawn darker. The marker is numeric, so any slider year from 2025 to 2055 draws. The y title and tooltip use `climate.units.hdd30` when present. Under the chart, a table shows the historical mean against the 2035-2055 mean for the chosen scenario for `hdd30`, `gdd` and `prcp_amj` (units from `climate.units` when present), with the change. The effect shown is `today + f * (climate - today)`, with lo and hi treated the same way. Its yield bar draws today's interval pale and the moved interval on top. If `in_support === false` and f >= 0.5, the card goes hatched with "Beyond evidence ... strip trial recommended" plus `analog_note`. From 2035 the inset map and list show `climate.analogs`; strategies that are out of support under the chosen scenario are listed in a hatched box. Other outcomes are not transported, because the contract has no climate values for them.

### Preference cards (Bradley-Terry)
The six pairwise cards are the 6 pairs among S0..S3 for the selected field type. Each "future" is a strategy's real estimates with its name hidden, and sides alternate. The choice model is `P(A over B) = sigmoid(w . (x_A - x_B))`, where x holds goodness-signed outcome estimates (yield, soil loss, drought loss, nitrate), each divided by its SD across all types and strategies. Weights get a MAP fit (Gaussian prior at equal weights, lambda = 1.5, projected gradient, w >= 0). Afterwards the panel shows normalised weights, a re-ranked list, re-ordered cards and a map recoloured by the new best strategy. It also shows "Evidence values changed by your answers: 0", computed by comparing every numeric leaf of `effects.json` against a snapshot taken at load. If the choices are contradictory (total weight < 1), the panel says the ranking is close to a tie. Checked in the browser: always picking higher yield gives weights yield 0.88 / soil 0.00 / drought 0.04 / nitrate 0.08.

### Map colouring
- **Best strategy**: the top of `rankStrategies(effects.by_type[type], weights)`. S0 may win.
- **Evidence**: the `badge_best` column while no preferences are set (I read it as *the evidence badge of the top-ranked strategy for the field's type*); after preferences, the badge of the recomputed best strategy. "Beyond" is drawn hollow, so colour is never the only signal.
- **Field type**: six categorical slots. A seventh type or more folds to grey. Note: per the dataviz rules, only 3 slots are CVD-safe for scatter maps, so the panel always names the type in words.

## Interpretations of under-specified contract fields (exporter please match or tell frontend)
- `fields_index.badge_best`: an evidence badge string (`strong|moderate|thin|beyond`). An `S0..S3` value would also be tolerated, because the app recomputes the best strategy from `effects`.
- `hindcast.by_type`: `[{type_id, actual:[sid...best->worst], causal:[...], rule_baseline:[...], correlational_ml:[...], n_fields?}]`. Optional `hindcast.units: {top1_regret, coverage}`.
- `badge_calibration`: `{badge:{strong:{empirical_error_rate, coverage, n}, moderate:..., thin:..., beyond:...}}`. A top-level map without the `badge` wrapper also works.
- `policy`: optional `value_unit` string. `tree[].recommended` is a strategy_id.
- `signpost`: optional `threshold_percentile` draws a hatched trigger zone on the percentile bar.
- `climate.json`: `scenarios.<ssp>.{years, gdd, hdd30, prcp_amj}`, per year (multi-model mean). The real pipeline covers 2035-2055, and any span that includes 2035-2055 works. `historical.{years, gdd, hdd30, prcp_amj}` per year for 1995-2014. Optional `units: {gdd, hdd30, prcp_amj}` (e.g. `"degC-days"`, `"mm"`) and optional `recent: {year, hdd30}`. `analogs` should be a list `[{lon, lat, state, label, distance}]`. The app also accepts the climate module's raw `analogs` block, reading `analogs.cells`.
- `field_types.types[].definition`: an object rendered as "key: value" under "How this type is defined". Arrays are joined with "-", e.g. `slope_pct: [3, 9]` becomes "3-9". A plain string also works.
- `effects.strategies[].description` and `applies_to` are shown under each card title.
- `fields_index.seq` letters follow `pipeline/cdl_fields.py`: C corn, S soybean, R other row crop, W wheat, O small grain, H hay/alfalfa/clover, P grass/pasture, X other, ? no data. The caption lists only the letters present.
- Null estimates: an outcome with `est: null` shows "not estimated", not a number. A strategy whose `climate.<ssp>` is null or has no numeric `est` shows "No 2035-2055 estimate exported for this strategy; showing today's evidence." In the ranking, a missing preference outcome counts as 0 (no change), and the cards and preference result then show "Ranking ignores missing outcomes (n not estimated)".
- `hero_fields.json` is a top-level array, so it cannot carry a top-level `"mock": true`. Mock hero entries have `"mock": true` on each element instead, and the app knows they are mock because they came from `web/mock/`.
- `ribbon.heat_risk` is drawn on a 0-1 scale (or its max if that is greater). `erosivity` is scaled to its peak month (the units are not in the contract).

## Mock data (`web/mock/`, written by `pipeline/frontend_mockdata.py`)
**Every number is synthetic.** Each file except `hero_fields.json` has `"mock": true` and a `note`. Seed 20261114, deterministic.
- `fields_index.json`: 26,752 rows on the real 480 m grid from `data/region.json` (UTM 15N to lon/lat via pyproj). Fields, types and counties are synthetic (types from smooth noise; counties from approximate boxes). Types: T1 10,882 · T2 6,613 · T3 3,238 · T4 1,997 · T5 2,114 · T6 1,908.
- `effects.json`: 6 types x S0..S3. All three estimators are included, along with climate for both SSPs (some cases out of support, to exercise the hatching) and plausible-looking magnitudes. Mock best strategy per type under default weights: T1 S1, T2 S2, T3 S2, T4 S1, T5 S3, T6 S3.
- Since this revision, `fields_index.json` reuses the **real** `is_field` mask, county names and `crop_seq_2016_2024` from `data/fields.parquet` (CDL module) when that file exists. That gives 26,323 rows: every real `is_field` sample, with the same ids the real export will use. Types, badges and every effect number stay synthetic. Mock types: T1 11,404 · T2 5,733 · T3 3,101 · T4 2,209 · T5 1,999 · T6 1,877.
- `hero_fields.json`: 2 heroes picked from `is_field` rows: f23608 (knoll, T3, Story County) and f04839 (T5, Hamilton County, real sequence CCCSCCCCC). Each has 8 twins (all `is_field`), a ribbon and a 2016-2024 synthetic control with a 2020 switch. The app drops, with a `console.warn`, any hero that is not in `fields_index`.
- `climate.json` now matches the real export's shape: historical 1995-2014 per year (with `years`), SSP2-4.5 and SSP5-8.5 per year for 2035-2055 only, `units` in degC-days and mm.
- `hindcast, policy, signpost, badge_calibration, meta, counties` (approximate boxes; real outlines are in web/data/).
- Sizes: fields_index 1.7 MB, everything else < 35 KB.

## Verification done
- Served with `http.server` and opened in the desktop app's browser pane, desktop width and 375 px mobile emulation, light and dark. A fresh tab showed **no console messages at all**. Earlier warnings ("circle-11", "wood-pattern", "Expected value ... null") came from my own in-page tests with the OpenFreeMap dark style, and the page also handles `styleimagemissing`.
- Mobile: no horizontal overflow (`scrollWidth == innerWidth == 375`). Outcome rows collapse to label + value with the bar below. The banner stops being sticky.
- Worked in the browser: hero selection, twin highlight and fit, synthetic-control chart, slider to 2048 with SSP5-8.5 (hatched "beyond" card, analog list and inset), the 6-card preference flow (re-rank, map recolour, "0 evidence values changed"), the hindcast reveal (score line "first choice right 5/6 vs 0/6 vs 1/6" on mock), the policy tree, sources and caveats, the voice summary text, and data/ taking precedence over mock/.

## Known caveats
- Speech uses the browser's default voice. If `speechSynthesis` is missing, the button is disabled with a tooltip.
- The climate transport is an interpolation along the CMIP6 heat path toward the exported 2035-2055 estimate. It never extrapolates past that estimate, and it moves only the yield effect.
- The hindcast reveal and hover colour/opacity transitions are the only motion. The reveal is instant under `prefers-reduced-motion`.
- The field-type colour mode uses 6 categorical hues, past the 3 that are CVD-safe for scatter, so the type is always named in words in the popup and panel.
- The map depends on tiles.openfreemap.org and the CDNs being reachable during the demo. For an offline demo, vendor `maplibre-gl.js/css` and `chart.umd.min.js` into `web/vendor/` and change the 3 tags in `index.html`.

## Exporter checklist (whoever writes web/data/)
1. Write every contract file with the same names as `web/mock/`, and without a top-level `"mock": true`.
2. `fields_index.rows`: all `is_field` samples. `hero_fields[].field_id` and `twins` must come from those rows; a hero that is not in `fields_index` is hidden.
3. `climate.json`: per-year multi-model means. `scenarios.ssp245/ssp585.{years, gdd, hdd30, prcp_amj}` covering 2035-2055, `historical.{years, gdd, hdd30, prcp_amj}` for 1995-2014, `analogs` as a flat list, plus optional `units`. From `data/climate_future.json`: average `per_year.<model>.<scenario>` over the 3 models (gdd = `gdd_may_sep`, hdd30 = `hdd30_jul_aug`, prcp_amj = `prcp_amj`), and analogs = `analogs.cells`.
4. `hindcast.by_type`: `[{type_id, actual, causal, rule_baseline, correlational_ml, n_fields?}]`, with strategy ids best to worst. Any other shape shows a "Per-type rankings exported in an unexpected shape" message.
5. `counties.geojson`: already handled by `pipeline/frontend_counties.py`. Re-run it if `data/counties.geojson` changes.

## Revision 2 (verifier fixes)
- Major: the climate time axis now matches the real pipeline (2035-2055 + 1995-2014). This revision changed the transport interpolation, switched the chart to a linear axis and reshaped the mock to match. Tested with a real-shaped `climate.json` built from `data/climate_future.json` and placed in web/data/ temporarily: slider years 2026-2055 all draw the marker, and the note says "heat interpolated ... from 2035 along the smoothed CMIP6 Jul-Aug heat trajectory".
- Major: `strategies[].description` and `applies_to`, `field_types.types[].definition`, and `climate.gdd` / `prcp_amj` are now all shown.
- Major: real county outlines are in `web/data/counties.geojson` via `pipeline/frontend_counties.py`, and counties alone never trigger the banner.
- Minor: heroes are filtered to `fields_index`, and mock heroes are real `is_field` ids; crop letters follow the CDL module; `climatology_years` renders as min-max; null estimates are handled; chart units come from `climate.units`; a message appears when the hindcast shape is wrong; `web/data/README.txt` was added.
- Variant test, using temporary files in web/data/ that were removed afterwards: a bogus hero f99999 is hidden and warned about; an S1 erosion estimate of null shows "not estimated" plus the ranking note; a null S2 SSP2-4.5 climate entry shows the "no 2035-2055 estimate" line; a full 1981-2024 year list shows "climatology 1981-2024"; a bad hindcast shape shows the message. There were no "n/a%" strings, no console errors and no 404s, and at 375 px scrollWidth == innerWidth.
