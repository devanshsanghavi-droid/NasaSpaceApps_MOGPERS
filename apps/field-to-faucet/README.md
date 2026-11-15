# Field to Faucet

**NASA satellites can see when farm fields upstream of Des Moines sit bare and wet and leak nitrate. Field to Faucet
shows each farmer when their field leaks and which rotation keeps the nitrogen in the field, and shows the city what
that means for the tap water of more than 600,000 people.**

NASA Space Apps 2026 · Challenge: "Field Shift: Adapting Farms with NASA Data". A static web app plus a reproducible
Python pipeline. Decision support, not a replacement for your agronomist.

Deliverables in this folder: [`PITCH.md`](PITCH.md) (7 slides + 30-second video), [`VALIDATION.md`](VALIDATION.md)
(out-of-time tests), [`CLAIMS.md`](CLAIMS.md) (every number, its source and status), [`BLOCKERS.md`](BLOCKERS.md)
(data we could not reach and what we used instead).

## Why it matters

- In 2025 the Raccoon River intake was above the 10 mg/L nitrate limit on **115 of 356 measured days** (USGS 05484500).
- Des Moines' nitrate-removal plant ran **112 days** in 2025 (about **$2.2M** including capital) and a record **193
  days** in 2026.
- Central Iowa Water Works imposed lawn-watering bans in both summers: **56 days** for all customers in 2025 and **42 days**
  for businesses and governments (23 days for homes) in 2026.
- Replaying 2025 with 25% more upstream acres under winter living cover gives about **23 fewer plant days (5-41)**,
  about **$350k** less operating cost ($73k-620k) and about **23 fewer ban days (9-31, indicative)**.

Sources and status for each number: [`CLAIMS.md`](CLAIMS.md).

## Run it

```
cd apps/field-to-faucet/web && python3 -m http.server 8000
# open http://localhost:8000/
```

- No build step, no CDN calls, no external map tiles. MapLibre GL JS 4.7.1 and Chart.js 4.4.6 are vendored in
  `web/vendor/`. All data is in `web/data/` (about 7 MB).
- Routes: `#city` (landing), `#farmer`, `#farmer/<field_id>` (deep link to a field), `#method`.
- **GitHub Pages:** publish the repository (or this branch) with Pages and open
  `https://<user>.github.io/<repo>/apps/field-to-faucet/web/`. All paths are relative. On `*.github.io` the loader
  requests each `data/` file directly, because Pages has no directory listing.
- If a data file is missing, the app falls back to `web/mock/` and shows a red **"MOCK DATA — not real"** banner naming
  the file. With the files in this repo, no mock data is used.
- Browser QA (Playwright, 1280 and 375 px, no console errors, no horizontal scroll):
  `node web/qa/run_qa.cjs http://localhost:8000/` → screenshots in `web/qa/`.

## The two views

**City / tap water (`#city`)**
- Headline for the replay year (2025 or 2026): plant days, cost, ban days, people served, each linked to its source.
- **Impact slider:** "1 in 4 more upstream fields keep living roots over winter" → fewer plant days, operating cost
  avoided and ban days, with 8-in-10 ranges.
- **Replay** of the measured river with more living cover, and the nitrate kept out of the river.
- **River record** 2016-2026 with the model's 8-in-10 band, shaded training, test and live periods.
- **Hotspot map** of the 290 upstream sub-watersheds (HUC-12s), shaded by share of the modelled leak.
- **14-day outlook** for the intake, with the chance of exceeding 10 mg/L on each day and the drivers behind it.

**Farmer (`#farmer`)**
- Map of 1,769 forty-acre fields in a 10-HUC-12 focus area on the North Raccoon (Sac and Calhoun counties area),
  shaded by modelled leak.
- **Leak calendar** for the selected field: bare ground (HLS), rain and big-storm days and root-zone wetness (NASA
  POWER), and when the leak happens.
- Living-cover curve (HLS NDVI) with the 0.30 threshold.
- **Strategy cards**: S0 current corn-soy, S1 cereal rye before soybean, S2 4-year corn-soy-oats-alfalfa, S3 prairie on
  about 10% of the field. Each card covers why, evidence (trials and satellite), lb N kept with range, fertilizer value,
  cost, yield risk, soil health, information gaps, risks for local review and who pays (EQIP, IDALS, Greater Des Moines
  Watershed, crop-insurance discount, CRP CP-43).
- **Priority sliders** (N kept, yield safety, soil, low net cost) re-rank the cards.

**Method (`#method`)**: validation tables against baselines, the 2025 miss, outlook skill, proxy-rule tests, data
sources (NASA tagged), caveats and file provenance.

## Data sources

NASA datasets are integral: they are the inputs from which the leak calendar, the river model, the hotspot map and the
outlook are built.

| dataset | provider | role | access used |
|---|---|---|---|
| **HLS v2.0** (Harmonized Landsat Sentinel-2, L30 + S30), 30 m | NASA LP DAAC | Living cover vs bare soil on every field (2020-2026); fills the Jul-Nov 2025 MODIS gap | Planetary Computer `hls2-l30`, `hls2-s30` |
| **MODIS 13Q1** Terra + Aqua NDVI v6.1, 250 m, 16-day (8-day combined) | NASA LP DAAC | Bare-soil share of row-crop land per basin and HUC-12 (2011-2026): river-model driver, hotspot index, scenario lever | Planetary Computer `modis-13Q1-061` |
| **NASA POWER** daily (MERRA-2; GEOS-IT for recent months), incl. **GWETROOT** root-zone wetness, GWETTOP, PRECTOTCORR, T2M, SNODP | NASA LaRC | Rain, soil wetness, snow and temperature: wet-soil drainage, river-model drivers, field leak calendar, outlook drivers | power.larc.nasa.gov API |
| **GPM IMERG** V06 half-hourly, 0.1° | NASA GES DISC / PPS | Check of POWER rain and storm intensity on 38 storm days, 2016-2021 | Planetary Computer `gpm-imerg-hhr` |
| **NASADEM**, 1 arcsec | NASA | Slope of fields and HUC-12s | Planetary Computer `nasadem` |
| USGS NWIS (05484500, 05482000; nitrate 99133, flow 00060) | USGS | Measured nitrate and flow: validation target, loads, and the series the scenarios change | waterservices.usgs.gov |
| USGS Watershed Boundary Dataset (HUC-12) | USGS | Basins draining to each intake, sub-watersheds | hydro.nationalmap.gov |
| USGS NHD / NHDPlus V2 flowlines (small scale) | USGS | Rivers on the maps | hydro.nationalmap.gov |
| USDA NASS Cropland Data Layer 2011-2025 | USDA NASS | Row-crop masks, crop sequences, crop shares | Planetary Computer `usda-cdl` (to 2021), NASS national zips (2022-2025) |
| gNATSGO / SSURGO | USDA NRCS | Drainage class (tile-drained proxy), hydrologic group | Planetary Computer `gnatsgo-rasters`, Soil Data Access |
| US Census TIGER cartographic boundaries, Gazetteer | US Census Bureau | Counties and towns on the maps | www2.census.gov |
| Iowa Nutrient Reduction Strategy (2024 practice efficiencies; 2025 edition) | Iowa State University / IDALS / Iowa DNR | Practice effects for cards and scenarios | nutrientstrategy.iastate.edu |
| Central Iowa Water Works, KCCI, Iowa Public Radio; ISU Extension; IDALS; USDA ARS | various | Plant days and cost, ban dates, people served, costs, cost-share, trial results | see `docs/facts.json` |

Data through: USGS 2026-11-13, POWER 2026-11-11, MODIS 2026-10-24, HLS 2026-10-29, CDL 2025.

Not used (blocked, see `BLOCKERS.md`): SMAP, ECOSTRESS, GRACE/GRACE-FO, IMERG after May 2021.

## Pipeline

Run from `apps/field-to-faucet/`. Every script is re-runnable, caches raw downloads in `data/raw/` (gitignored) and
prints a short report. Times are approximate on 4 CPUs (first run / cached).

**Data (`pipeline/`)**

| step | script | output | time |
|---|---|---|---|
| 1 | `p01_wbd.py` | basins + 290 HUC-12s (`huc12.parquet`, `web/data/basins.geojson`, `huc12.geojson`, `sites.json`) | under a minute |
| 2 | `p02_nwis.py` | `nwis_daily.parquet` (USGS nitrate, flow, load, 2015-10 to latest) | ~20 s |
| 3 | `p03_power.py` | NASA POWER per cell and per basin, 2015 to latest | ~1 min / ~10 s |
| 4 | `p04_web_context.py` | `rivers.geojson`, `counties.geojson`, `places.json` | ~15 s |
| 5 | `p05_cdl_fetch.py` | CDL 2016-2025 on one 30 m grid | ~8 min |
| 6 | `p06_cdl_shares.py` | crop shares per basin and HUC-12 | ~1 min |
| 7 | `p07_soils_terrain.py` | gNATSGO drainage, NASADEM slope per HUC-12 | ~2 min |
| 8 | `p08_modis_mask.py` | persistent row-crop mask on the MODIS grid | ~40 s |
| 9 | `p09_modis_cover.py` | MODIS bare/living share per basin and HUC-12 (8-day, daily, causal as-of) | ~5 min / ~40 s |
| 9b | `p09b_hls_gapfill.py` | HLS fill of the 17 missing Jul-Nov 2025 MODIS composites (re-runs p09) | ~7 min / ~1 min |
| 10 | `p10_focus_area.py` | `focus_area.json` (10 HUC-12s in HLS tile 15TUG) | ~5 s |
| 11 | `p11_hls_fetch.py` | HLS reads of the focus area, 2020-2026 (591 granules) | ~12 min / incremental |
| 12 | `p12_fields.py` | `fields`, `hls_field_ts`, `field_month`, `field_year` | ~25 s |
| 13 | `p13_hls_vs_modis.py` | `hls_vs_modis.json` | ~5 s |
| 14 | `p14_imerg.py` | IMERG storm-day sample vs POWER (8.3 GB read once) | ~5 min / ~5 s |
| 15 | `p15_earthdata_check.py` | CMR granule availability for SMAP, IMERG V07, ECOSTRESS, GRACE | ~1 min |
| 16 | `p16_smap_optional.py` | SMAP L4 root-zone moisture if Earthdata credentials exist; otherwise exits cleanly | instant |

**Models (`model/`)**, in this order:

| step | script | output | time |
|---|---|---|---|
| 1 | `m01_features.py` | causal daily features (v1) | ~2 s |
| 2 | `m02_river_model.py` | v1 river model, baselines, `metrics.json`, `river_daily.parquet` | ~4 min |
| 3 | `m03_sensitivity.py` | learned response to less bare soil (v1) | ~30 s |
| 4 | `m04_outlook.py` | 14-day outlook + skill | ~2 min |
| 5 | `m06_history.py` | 2008-2015 USGS, POWER, MODIS, CDL for v2 | ~6 min cold |
| 6 | `m07_features_v2.py` | v2 features with the N carry-over store | ~10 s |
| 7 | `m08_v2.py` | v2 river model, strict check, blind 2013 check, display rule | ~15 min |
| 8 | `m03_sensitivity.py --v2` | v2 sensitivity | ~30 s |
| 9 | `m05_figures.py` | `model/out/fig_*.png` | seconds |
| 10 | `m05_fields.py` | drainage fit, loads, field and HUC-12 leak, calibration, validation check | ~30 s |
| 11 | `m06_strategies.py` | strategy cards + per-field N kept (Monte Carlo) | ~30 s |
| 12 | `m07_scenarios.py` | what-if engine (`scenarios.json`) | ~40 s |
| 13 | `m08_export_web.py` | all `web/data/*.json` contract files | ~2 s |

Libraries: `model/featlib.py` (causal features), `qgbm.py` (monotone quantile LightGBM), `reservoir.py` (conceptual
model), `river.py` (prediction and perturbation API). Python 3.13 with numpy, pandas, scipy, scikit-learn, lightgbm,
rasterio, pystac-client, planetary-computer, xarray, zarr, geopandas, shapely, pyarrow.

## Method summary

**Living-cover detection.**
- *Fields (HLS):* a field is a 400 m grid cell (about 40 acres) that is at least 80% one row crop in 7 of 10 CDL years.
  A clear observation is "living" when the cell's median NDVI ≥ 0.30 (pixels flagged cloud, shadow or snow removed;
  Sentinel-2 high-aerosol pixels masked Oct-May; Sentinel-2 harmonised to Landsat by −0.0076 NDVI in the dormant
  season; whole-scene spikes removed). Daily status is interpolated between clear views (gaps up to 120 days).
  Thresholds 0.25 and 0.35 were tested: 0.35 gives nearly the same answer; 0.25 flags bare residue.
- *Watershed (MODIS):* share of valid persistent row-crop pixels with NDVI < 0.30 per 16-day composite, with a causal
  "as-of" series (only composites already published on each day). MODIS is used as a relative index; HLS for absolute
  field values (`VALIDATION.md` §10).

**River model.**
- *v1 (pre-registered):* monotone quantile gradient boosting of ln(nitrate), non-decreasing in bare share and soil
  wetness, inputs from POWER, MODIS, CDL and USGS flow, never measured nitrate. Train 2016-2022, test 2023-2025, live
  2026. Baselines: climatology, a two-reservoir conceptual model, 7- and 14-day persistence.
- *v2 (post-hoc):* adds a causal nitrogen carry-over store (builds in dry years, flushed by wet soil) and, for the
  Raccoon, the 2012-2015 record. Shown on the chart by a rule fixed before any 2026 metric.
- *Outlook:* quantile models of the 1-14-day change from the last measurement; no weather forecast.

**Field leak calibration.**
- Daily wet-soil drainage = (rain + snowmelt) × a gate that opens as POWER root-zone wetness rises from 0.45 to 0.55
  (fitted to measured runoff: monthly r 0.91).
- Leak = [bare + 0.232 × living] × drainage × (1 + 1.5 × poorly drained share), summed per HUC-12 and field. The 0.232
  makes HLS-detected cover fields leak 28% less, the INRS 2024 rye efficiency.
- Each year, HUC-12s and fields are scaled so their sum equals the measured river load times the row-crop share of river
  nitrate (0.76-0.89, from INRS and CDL). The median field leaks 13.7 lb N/acre/yr long-run (8.8-20.0 across fields);
  poorly drained fields about 1.35× more than well-drained ones.

**Scenario engine.**
- Lever: X% additional upstream row-crop acres with a cereal-rye-type cover Oct-May (X = 0-50%), on top of today's
  ~17% statewide adoption.
- Each day's **measured** nitrate is cut by a fraction from two lines of evidence, half of 4,000 Monte Carlo draws each:
  (a) Iowa trials (INRS 2024 rye 28%, SD 26) × row-crop share of river nitrate; (b) our river model's response when bare
  share is cut by X on Oct 15-May 31.
- Plant and ban days come from proxy rules fitted to 2025 and tested on 2026; cost = plant days × $14,286-16,000
  (operating only).
- Results are p50 and the 10th-90th percentile.

**Strategy cards.** Practice efficiency (INRS 2024, truncated normal) × the field's own modelled leak distribution ×
how often the practice applies (rye before soybean only in soybean-after-corn years), as Monte Carlo. Headline = long-run
mean lb N/acre/yr; range = single-year 10th-90th percentile.

## Validation headline

Full detail: [`VALIDATION.md`](VALIDATION.md).

| | Raccoon (05484500) | Des Moines (05482000) |
|---|---|---|
| v1 test NSE 2023-25 (climatology) | **0.62** (0.30) | **0.56** (0.27) |
| 2025 days above 10 mg/L: measured / v1 / v2 (post-hoc) | 115 / **6** / 83 | 105 / **10** / 10 |
| Blind 2013 check: measured / v2 | 92 / 81 | – |
| Outlook MSE skill vs persistence, 7 / 14 days (test) | +20% / +25% | +37% / +17% |
| Outlook Brier skill at 14 days vs probabilistic persistence | +0.03 (none) | −0.04 (none) |
| Plant proxy, fitted 2025 → tested 2026 | 157 of 193 run days, F1 0.90 | |

The leak index tracks year-to-year river load (r = 0.75), but no better than water alone, and the bare-soil term adds
no interannual skill (partial r −0.39). Practice effects come from trials. The HUC-12 hotspot ranking is not validated.

## Limitations

1. **The 2025-26 level is not explained.** The rivers carried 1.7-2.1× the nitrate the drivers explain. Legacy nitrogen
   after the 2020-2023 drought is a hypothesis; scenarios therefore change the measured river by a relative amount.
2. **Practice effects come from Iowa trials,** with large spreads (rye 28 ± 26%). The learned river response to bare
   soil is weakly identified: past cover changes were almost all seasonal.
3. **Proxy rules.** The utility's plant and ban rules are not public. Ban-day results are indicative; demand, heat and
   treatment capacity also drive bans.
4. **Cost** is operating cost only; the ~$40M plant expansion is not avoided.
5. **Fields are 40-acre grid cells.** N rate, manure, tile layout and tillage are unknown. Cover detection is a lower
   bound (thin rye below NDVI 0.30 is missed).
6. **Coarse weather.** POWER is about 50 km and smooths storm peaks; continuous IMERG and SMAP were not reachable.
7. **Des Moines River** sits below Saylorville Reservoir, which is not modelled; it is the weaker site in every test.
8. **Legacy nitrate** means a field change takes more than one season to show in the river; results describe a fully
   developed effect replayed on past weather.
9. **Provisional data.** USGS values from 2026-06-02 on are provisional and can be revised.
10. **No sub-basin gauges,** so the hotspot map shows "where bare ground meets wet soil", not measured sources.

## Repository layout

```
apps/field-to-faucet/
  README.md  PITCH.md  VALIDATION.md  CLAIMS.md  BLOCKERS.md  CONTRACTS.md
  docs/facts.json, facts_notes.md      utility, trial and program facts with source URLs and verification
  notes/*.md                           per-module method notes (hydro, cdl, modis, fields, storms, model,
                                       fields_model, scenarios, frontend)
  pipeline/p01..p16_*.py               data pipeline (+ common.py, fields_common.py)
  model/m01..m08_*.py                  models, scenarios, export (+ featlib, qgbm, reservoir, river)
  model/out/                           metrics.json, sensitivity.json, outlook.json, scenarios.json,
                                       basin_index_check.json, fig_*.png, model files
  data/processed/                      small processed tables (parquet/json); data/raw/ is gitignored
  web/                                 static app: index.html, css/, js/, data/, vendor/, mock/, qa/
```

## Licence and attribution

- **Vendored libraries:** MapLibre GL JS 4.7.1 (BSD 3-Clause, © MapLibre contributors; `web/vendor/maplibre-gl-4.7.1/LICENSE.txt`)
  and Chart.js 4.4.6 (MIT, © Chart.js Contributors; `web/vendor/chart.js-4.4.6/LICENSE.md`). Both were taken from the
  npm tarballs with their licence files kept.
- **Data:** NASA HLS, MODIS, POWER, GPM IMERG and NASADEM are NASA open data (HLS DOIs 10.5067/HLS/HLSL30.002 and
  10.5067/HLS/HLSS30.002; MODIS via LP DAAC; POWER: "These data were obtained from the NASA Langley Research Center
  POWER Project"). USGS (NWIS, WBD, NHD), USDA (CDL, gNATSGO/SSURGO) and Census data are US public domain. Planetary
  Computer was used as an access mirror for HLS, MODIS, IMERG, NASADEM, CDL and gNATSGO.
- News and utility pages (CIWW, KCCI, IPR) are cited by URL for individual facts; no content is redistributed beyond
  short quotes in `docs/facts.json`.
