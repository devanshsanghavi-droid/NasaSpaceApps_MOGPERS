# Module: frontend (web/)

A static app in `web/`, with plain ES modules and no build step. Libraries are vendored and pinned in `web/vendor/`: MapLibre GL JS 4.7.1 and Chart.js 4.4.6 (npm tarballs, LICENSE kept, `sourceMappingURL` removed). No CDN calls, no external tiles: maps are drawn only from our own GeoJSON.

## Run
```
cd apps/field-to-faucet/web && python3 -m http.server 8731      # open http://localhost:8731/
node qa/run_qa.cjs http://localhost:8731/ [--shots-dir=DIR]     # Playwright QA + screenshots into web/qa/
```
Routes: `#city` (landing), `#farmer`, `#farmer/<field_id>` (deep link), `#method`.

## Status: all data real
Every file in `web/data/` is real (written by `model/m08_export_web.py`). The mock fallback (`web/mock/`) is still in the loader but unused: QA asserts that no MOCK banner and no MOCK chip is visible on any view.

## Structure
| File | Role |
|---|---|
| `index.html` | Shell: mock banner, tab bar, three views, footer |
| `css/app.css` | Tokens: ink/ground, one accent (teal `#0b5f66`), nitrate red `#c0322b`, warm sequential leak ramp `--leak-0..5`, blue sequential driver ramp. Breakpoints 960 / 560 px |
| `js/main.js` | Creates the store, renders views, hash router; re-renders banner + provenance after each lazy group loads |
| `js/data.js` | Grouped/lazy loader, mock fallback, banner, provenance, `factsMap` (resolves `aliases`), `getFieldDetail`, `nasaStrip` |
| `js/city.js` | Impact hero + year switch, KPI strip, replay chart, river chart + honest line, hotspot map, outlook |
| `js/farmer.js` | Field map, field facts, leak calendar, NDVI, priorities, strategy cards and ranking |
| `js/method.js` | Honest miss, validation tables, outlook skill, proxy-rule test, sources, caveats, provenance |
| `js/charts.js` | Chart.js on a linear ms time axis; split shading, threshold line, crosshair, band tooltip (`bandLabel`). Nulls are gaps |
| `js/map.js` | Blank-style MapLibre, HTML-marker labels, quantile `step` colouring, ramp legend |
| `js/util.js` | Formatting (`meanBand`, `shareAsFreq`, `fmtLbAc`, `linkify`), natural frequencies, segmented control |

## Loading (first-view weight)
| Group | Files | When |
|---|---|---|
| core | meta, facts, scenarios, sites | before first render (hero, KPIs, slider, replay) |
| river | river_series, validation, outlook | right after the hero is drawn (river chart, outlook, method view) |
| map | huc12, basins, rivers, places, counties (~0.6 MB) | right after first render (city map + hotspots) |
| farm | fields.geojson, strategies (~0.68 MB) | only when the farmer view opens (tab, deep link or sample button) |
| detail | field_index.json (42 KB) + field_detail/<huc12>.json (0.2–0.8 MB) | on first field click; HUC-12 from the index (fallback: the field's `huc12` prop) |

First view (`#city`, network idle, uncompressed from `http.server`): 28 requests, ~3.0 MB, of which ~1.0 MB is vendored JS (now `defer`). No farmer data is fetched on the city view (QA asserts it). If Chart.js or MapLibre fail to load, a `#lib-banner` says so and charts/maps show an in-place message (`timeChart` returns null; `createMap` resolves null).

## City view (impact first)
- **Hero h1** (replay year Y, all numbers from facts.json via aliases, never hard-coded):
  `Nitrate from upstream — mostly farmland — forced Des Moines to run its nitrate-removal plant [a record] N days [(Jan–Jul)] and impose a lawn-watering ban of up to 56 days (homes: 40) in 2025.` + second line `NASA satellites show which fields sit bare on wet soil — and when.`
  - 2026 (ban fact label names the business count): `… a record 193 days (Jan–Jul) and impose a lawn-watering ban of 23 days for homes, 42 for businesses, in 2026.` The run-month span comes from the plant fact's dates, partial years only.
  - Source note under the h1 (`#city-h-src`): "Why 'mostly farmland': statewide, 92% of the nitrogen entering Iowa streams comes from nonpoint sources, mostly farmland (INRS; fact inrs_nonpoint_share_pct). Not measured for Des Moines alone." Never attribute the plant days to "bare fields" directly.
  - Gauge 05484500 is the Raccoon River at Van Meter, upstream of the intake: never "at the intake". The 10 mg/L limit is a drinking-water standard; the tap met it.
- **NASA one-liner** above the slider: "Seen from space: bare soil (NASA HLS: Landsat + Sentinel-2) + wet soil (NASA POWER) = when nitrate leaks."
- **Impact card**: label "Try it: cover on 1 in 4 of all upstream corn/soy acres, beyond the ~17% already covered (25%)" (17% = fact `iowa_cover_share_pct`). Sentence and 4 tiles in this order: nitrogen "kept out of the rivers (measured at the gauges)" (`avoided.lbN_kept`; a gauge load, not on-field retention), plant days ("16 fewer plant days"), ban ("~3 weeks shorter", weeks when ≥ 10.5 days, otherwise days, pluralised), "up to ~$X" operating cost avoided (upper estimate: avoided days are often lower-output days; lower check `avoided.cost_usd_q1_2026_rate` at CIWW's Q1-2026 ~$8.4k/run day). Under each tile a "trials only: …" line from `levels[x].trials_only.avoided` when present. Ban label has the proxy-rule tooltip (clamped to the viewport by `initTips`). Fine print: `x_definition`, n_draws, $/day, today's cover, HLS winter-cover detection (~1–4% of focus-area fields, a lower bound; from `scenarios.hls_winter_cover_pct` / fact `hls_winter_cover_pct` if exported, else the fields-module rate), legacy-N lag. Sliders carry `aria-valuetext`; only `#impact-text` is `aria-live`.
- **Year switch**: `Replay 2025 | Replay 2026` from `scenarios.replays` ∩ `by_year`; drives hero, KPIs, replay and the river "year" range.
- **What NASA sees** strip (also on Farmer and Method): HLS, MODIS, NASA POWER (GWETROOT), GPM IMERG, NASADEM, matched by name in `meta.sources`, with links and `data_through`.
- **KPI strip** ("The Y record, with sources"): days the Raccoon River at Van Meter (upstream of the intake) was above the 10 mg/L drinking-water limit (USGS link), plant days (fact link; 2026 "(Jan–Jul) — longest run on record (previous most: 177 days in 2015)"), cost ("incl. capital" with O&M/capital split; 2026 "$1.6–3.1M (estimate)" = 193 days × ~$8.4k (fact `plant_cost_per_day_2026_q1_usd`, $660k / 79 Q1 run days) to ~$16k/day), ban days (2025 "up to 56 (homes: 40)", 2026 "23 for homes, 42 for businesses"; links the `ban_days_Y` fact), people served.
- **Replay chart**: "Measured, today's fields" = `replays[Y].obs` (base_kind observed); "With X% more living cover" = `by_level[x]`; teal fill between = "nitrate kept out of the river"; optional checkbox shows the scenario band `by_level_lo/hi`; 10 mg/L line. If a future export has `base_kind` ≠ observed, a dashed model baseline is added. Side tiles: days > 10 avoided (Raccoon, Des Moines), t N kept, lb N kept sentence.
- **River chart**: display model per site from `river_series.sites[s].model.model` → `display_model` (river_series or validation); legend "Model v2 (+ drought carry-over), median". Above it the honest line, built from validation numbers (mean test NSE of v1 `gbm`, 2025 `level_ratio_obs_over_model` min–max): "The weather-and-cover model explains normal years (test NSE ~0.6) but under-predicted 2025-26 by about 1.7–2.1× — likely nitrate left over after the 2020-23 drought (a hypothesis). That's why impact numbers replay the measured river with relative changes." Caption names USGS + NASA POWER/MODIS/HLS + CDL, and says v2 is post-hoc.
- **Outlook**: gauge toggle from `outlook.sites`. Headline "Already above the limit (…). Expect about N of the next 14 days above 10 mg/L" (`expected_days_over10` or Σ prob). Skill line: "No weather forecast used"; 7-day error skill vs persistence; Brier skill at 14 days (< 5% → "no probability skill"). Probability cells beyond the last lead with Brier skill ≥ 5% (from `validation.outlook_skill`) are faded.
- **Hotspot map**: popup ("Modelled leak", `n_in_basin`) with `maxWidth: min(280px, 80vw)`; list clicks anchor it to the left of the centre on wide maps. Note: "account for about X% of the modelled leak index (not measured)". Attribution starts collapsed; fitBounds has 40 px bottom padding; `cooperativeGestures` on coarse-pointer (touch) devices.
- **Outlook skill line**: "typical error N% smaller than 'no change' (squared error M%)": N from the h7 RMSEs of gbm vs persistence in `validation.outlook_skill`. Faded (no-skill) probability cells are hatched with ≥ 4.5:1 text, not opacity.

## Farmer view
- Buttons: **pick a sample field** = a TYPICAL field (closest to the median modelled leak), then **show a leaky field** (top-decile poorly drained, cycles). Field search (`#field-find`, datalist of towns + field IDs; a town picks its nearest field) and an `aria-live` announcement (`#field-live`). Bad deep link → "Field “X” not found." A missing `field_detail/<huc12>.json` sets `source.field_detail = "missing"` (amber banner) and the panel says which file failed.
- Field names for humans: "Field near <nearest town from places.json> (F01587)", sub-line "9 km west of Rockwell City, in <HUC-12>".
- Headline leak = `leak.lbN_ac_yr.mean`, labelled "modelled leak (estimate, not measured)", "p10–p90 lb in 8 of 10 years (dry years deliver little to the river that year; nitrate can leave later)"; red 2016 block; `why_field`.
- Leak calendar unchanged (month letters and hatched cells now ≥ 4.5:1 contrast).
- **Comparison table** (`#strategy-compare`, ranked order): N kept lb/ac/yr (long-run mean), cost $/ac/yr, cost-share $/ac (facts whose URL is one of the strategy's `who_pays` programs and whose id names cost-share/EQIP; otherwise "program listed, rate not verified"), yield risk, soil benefit (first benefit + count).
- **Cards**: headline N kept + bar + wet-year line; money line where cost and cost-share are both known ("Costs $12–$28/acre a year ($24–$55 each time it is planted); cost-share of $20–$74/acre (state $20–$30; EQIP ~$74, third-party figure) can cover much of it", source links with fact ids; cost from strategies.json `cost_usd_ac`; cost-share low end = fact `range.lo`; the verdict uses only agency-verified rates; `source_kind` third_party → "third-party figure"). Rye trial line: "INRS 2024 update: 28% (SD 26) cut in drainage nitrate concentration averaged across the rotation, 30% (SD 27) in the soybean year" (facts `inrs_cover_rye_pct.inrs_2024_update`, `inrs_rye_soy_year_pct/_sd`); fertilizer value, yield risk; Why. Folded `<details>` (closed): Yield/cost/fertilizer notes, Evidence, Soil-health benefits, What we don't know yet, Check locally, Who pays.
- **Ranking**: unknown inputs excluded (score = Σ known w·s ÷ Σ known w). No known weighted input or all weights 0 → "not scored" (never 0/100) and a prompt to move a slider. The formula box is gone from the sidebar; "How we rank" keeps it.

## Method view
Honest miss block (same line + `crisis_2025.text`), `validation.lines` (minus the ones already quoted), per-site test table (v1, v2 "shown in charts", reservoir, climatology, persistence; days > 10 measured/called), "Our models in every period" (train row = leave-one-year-out CV, v2 test/live marked post-hoc), blind 2013 check, outlook skill table (1/3/7/10/14 days), plant/ban proxy fit-2025/test-2026 table, sources, caveats, provenance.

## Contract interpretations (exporters: please match or tell frontend)
- `scenarios.x_definition` (string, or `{text|label}`) and `levels[].trials_only.avoided.<key>` (or `trials_only.<key>`), keys `lbN_kept`, `plant_days`, `ban_days`, `cost_usd`.
- Optional `scenarios.hls_winter_cover_pct` (number or `{lo,hi}`) for the HLS detection note.
- `facts.json` `{facts:{id:{…}}, aliases:{key:id}}`; keys used: people_served, plant_days_Y, plant_cost_Y_usd, plant_om_cost_Y_usd, ban_days_Y (+ `range.lo` = homes), plant_days_record_prior, iowa_cover_share_pct, fert_price_usd_lb_N.
- `scenarios.replays{Y}` preferred over `replay`; `thresholds.cost_per_plant_day` is `{lo,hi}`.
- The hero's "businesses" wording depends on the ban fact label containing "<N> days for business"; a structured `homes_days` / `business_days` field would be sturdier.

## QA (`qa/run_qa.cjs`)
1280×860 (deviceScaleFactor 2), 768×1000 (1), 375×760 (2), `--use-angle=swiftshader`. Asserts no console errors/warnings, no failed/≥ 400 requests, no MOCK/missing/library banner, no MOCK chips, no horizontal scroll, no `NaN`/`undefined`/`null`/`Infinity` in visible text (each view, slider at 0 and 25%, 2026), ban tooltip and hotspot popup inside the viewport, canvases `role="img"`, slider `aria-valuetext` and not inside `aria-live`, no in-page link with `target`. City: hero wording (2025 and 2026, INRS source note), no "at the intake"/"kept on fields"/"already paid" text, Van Meter gauge naming, 2026 "$1.6–3.1M" + record wording, KPI "incl. capital" / 2026 "estimate", homes figure, CIWW ban link, tile order (nitrogen first), pluralisation, 0% legend, slider sync, band toggle, year switch, river toggles, hotspot note, outlook "typical error". Farmer: cost-share "$20–$74 (state $20–$30; EQIP ~$74, third-party figure)", rye 28%/30% trial wording, typical sample first ("Field near … (F…)"), leaky second, live announcement, comparison rows = cards, money line, closed details, no formula box, re-rank, all-zero weights → prompt/"not scored", search by ID and town, map click, deep link, bad deep link "not found". Method: honest line ("one hypothesis"), "no weather forecast". Result: **QA OK**.

Deck screenshots (Pillow-quantised to 128 colours, each < 1 MB): `qa/city-hero-1280.png`, `city-full-1280.png`, `city-replay-1280.png`, `city-hotspots-1280.png`, `farmer-panel-1280.png` (typical field), `farmer-cards-1280.png` (table + cards), `method-1280.png` (to the end of validation), `city-375.png` (hero to KPIs), `farmer-375.png` (field head + calendar). `--shots-dir=DIR` adds river/map/outlook/2026-hero shots.
