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
| core | meta, facts, scenarios, river_series, validation, outlook, sites (~0.83 MB) | before first render |
| map | huc12, basins, rivers, places, counties (~0.6 MB) | right after first render (city map + hotspots) |
| farm | fields.geojson, strategies (~0.68 MB) | only when the farmer view opens (tab, deep link or sample button) |
| detail | field_index.json (42 KB) + field_detail/<huc12>.json (0.2–0.8 MB) | on first field click; HUC-12 from the index (fallback: the field's `huc12` prop) |

First view (`#city`, network idle, uncompressed from `http.server`): 28 requests, ~2.96 MB, of which ~1.0 MB is vendored JS. No farmer data is fetched on the city view (QA asserts it).

## City view (impact first)
- **Hero h1** (replay year Y, all numbers from facts.json via aliases, never hard-coded):
  `Y: Des Moines' nitrate removal plant ran [a record] N days (cost); 600,000+ people faced a lawn-watering ban …`
  - cost: `plant_cost_Y_usd` → "~$2.2M incl. capital"; no fact (2026) → `plant days × thresholds.cost_per_plant_day{lo,hi}` → "~$2.8–3.1M operating cost, estimate".
  - "a record" when plant days > `plant_days_record_prior`.
  - ban: homes vs all from `observed.ban_days_homes` (or fact `range.lo`). If the fact label says the headline count is the business one (2026) → "(23 days for homes, 42 for businesses)"; otherwise (2025, all-customer Stage III window) → "of up to 56 days (40 for homes)".
  - "600,000+" when the people fact says "more than".
- **Impact card**: slider (synced with the replay slider) and the sentence "If 1 in 4 more upstream fields kept living roots over winter: about N fewer plant days (range a–b), ~$X operating cost avoided, ~M fewer ban days indicative (proxy rule)". From `levels[x].avoided.{plant_days,cost_usd,ban_days}` (p50, lo, hi). $ is labelled "operating cost avoided (estimate)". The ban label is a hover/focus/tap tooltip with `thresholds.ban_rule` and the 2026 test (`calibration.ban.test_2026`: 40 proxy vs 42 real days). Fine print: n_draws, $/day range, "capital not avoided", today's ~17% cover (fact `iowa_cover_share_pct`), legacy-N lag.
- **Year switch**: `Replay 2025 | Replay 2026` from `scenarios.replays` ∩ `by_year`; drives hero, KPIs, replay and the river "year" range.
- **What NASA sees** strip (also on Farmer and Method): HLS, MODIS, NASA POWER (GWETROOT), GPM IMERG, NASADEM, matched by name in `meta.sources`, with links and `data_through`.
- **KPI strip** ("The Y record, with sources"): days > 10 (USGS link), plant days (fact link), cost ("incl. capital" with O&M/capital split; 2026 "estimate"), ban days (links the `ban_days_Y` fact), people served.
- **Replay chart**: "Measured, today's fields" = `replays[Y].obs` (base_kind observed); "With X% more living cover" = `by_level[x]`; teal fill between = "nitrate kept out of the river"; optional checkbox shows the scenario band `by_level_lo/hi`; 10 mg/L line. If a future export has `base_kind` ≠ observed, a dashed model baseline is added. Side tiles: days > 10 avoided (Raccoon, Des Moines), t N kept, lb N kept sentence.
- **River chart**: display model per site from `river_series.sites[s].model.model` → `display_model` (river_series or validation); legend "Model v2 (+ drought carry-over), median". Above it the honest line, built from validation numbers (mean test NSE of v1 `gbm`, 2025 `level_ratio_obs_over_model` min–max): "The weather-and-cover model explains normal years (test NSE ~0.6) but under-predicted 2025-26 by about 1.7–2.1× — likely nitrate left over after the 2020-23 drought (a hypothesis). That's why impact numbers replay the measured river with relative changes." Caption names USGS + NASA POWER/MODIS/HLS + CDL, and says v2 is post-hoc.
- **Outlook**: gauge toggle from `outlook.sites`. Headline "Already above the limit (…). Expect about N of the next 14 days above 10 mg/L" (`expected_days_over10` or Σ prob). Skill line: "No weather forecast used"; 7-day error skill vs persistence; Brier skill at 14 days (< 5% → "no probability skill"). Probability cells beyond the last lead with Brier skill ≥ 5% (from `validation.outlook_skill`) are faded.
- **Hotspot map**: unchanged; popup adds `lbN_ac_yr` and uses `n_in_basin`.

## Farmer view
- Headline leak = `leak.lbN_ac_yr.mean` (long-run average), "p10–p90 lb in 8 of 10 years"; red block "In a wet year like 2016: … lb N/acre" from `leak.wet_year_2016`; `why_field` shown.
- Leak calendar rows: bare (HLS), rain, big-storm days, soil wetness, leak risk, **Leak, lb N/acre** (`leak_lb_ac`). Months with `interp_only` are hatched grey in the bare row and the header ("no clear satellite view"). The sentence also says what share of the yearly loss falls in the riskiest window.
- Cards: headline `lbN_kept_ac.mean`, bar p10–p90, "In a wet year like 2016" (`wet_year_2016.lbN_kept_ac`), fertilizer value mean "(upper bound)" + `fert_value_note`, cost with basis and source link, `S1.note` when present. Evidence/who-pays/gaps text is linkified; every item links its URL.
- **Ranking fix**: a null `cost_usd_ac.lo/hi` is UNKNOWN: excluded from the min-max normalisation and from that option's weighted sum (score = Σ known w·s ÷ Σ known w). The card shows "cost not verified" and "Ranked without: low net cost (unknown)". The formula is shown under the sliders and in "How we rank".
- Agronomist note kept (hero + strategies disclaimer).

## Method view
Honest miss block (same line + `crisis_2025.text`), `validation.lines` (minus the ones already quoted), per-site test table (v1, v2 "shown in charts", reservoir, climatology, persistence; days > 10 measured/called), "Our models in every period" (train row = leave-one-year-out CV, v2 test/live marked post-hoc), blind 2013 check, outlook skill table (1/3/7/10/14 days), plant/ban proxy fit-2025/test-2026 table, sources, caveats, provenance.

## Contract interpretations (exporters: please match or tell frontend)
- `facts.json` `{facts:{id:{…}}, aliases:{key:id}}`; keys used: people_served, plant_days_Y, plant_cost_Y_usd, plant_om_cost_Y_usd, ban_days_Y (+ `range.lo` = homes), plant_days_record_prior, iowa_cover_share_pct, fert_price_usd_lb_N.
- `scenarios.replays{Y}` preferred over `replay`; `thresholds.cost_per_plant_day` is `{lo,hi}`.
- The hero's "businesses" wording depends on the ban fact label containing "<N> days for business"; a structured `homes_days` / `business_days` field would be sturdier.

## QA (`qa/run_qa.cjs`)
1280×860 and 375×760, `--use-angle=swiftshader`, deviceScaleFactor 1. City: hero/impact text checks ("incl. capital", "estimate" for 2026), ban tile link, hero↔replay slider sync, band toggle, year switch 2025→2026→2025, river toggles, hotspot popup. Farmer (tab click): sample field, ≥ 3 cards, "in 8 of 10 years", wet-year block, "cost not verified", lb row, agronomist note, priorities re-rank, map click, deep link. Method (tab click): honest line, "no weather forecast". Asserts no console errors/warnings, no failed/≥ 400 requests, no MOCK banner/chips, no horizontal scroll, no farmer data on the city view; prints first-view transfer. Result: **QA OK**.

Screenshots (quantised to 128 colours): `qa/city-hero-1280.png`, `qa/city-full-1280.png`, `qa/farmer-panel-1280.png`, `qa/method-1280.png`, `qa/city-375.png`, `qa/farmer-375.png`. `--shots-dir` adds section shots (replay, river, map, outlook, 2026 hero) elsewhere.
