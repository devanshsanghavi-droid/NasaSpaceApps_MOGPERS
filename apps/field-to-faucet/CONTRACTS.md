# Field to Faucet: build contract (every agent reads this first)

Spec (source of truth): `docs/concepts/field-to-faucet.md`. Rules: `docs/BUILD_RULES.md`. Data notes: `docs/DATA_ACCESS.md`,
`shared/central_iowa_pipeline/notes/*.md` (reuse ideas and code; copy into this app rather than importing from `shared/`).
Trial priors: `shared/evidence/evidence_priors.json`.

App root: `apps/field-to-faucet/` (paths below are relative to it). Python: system `python3` (3.13). Packages installed:
numpy pandas scipy scikit-learn lightgbm rasterio pystac-client planetary-computer xarray zarr cftime geopandas shapely
pyarrow fsspec aiohttp h5netcdf requests. Install more with `pip install -q <pkg>`. Machine: 4 CPUs, 15 GB RAM, ~30 GB disk.
Keep compute modest: use at most 6 worker threads for network reads, and never hold more than ~3 GB in memory.

## Hard rules
- **Real data only.** Never fabricate or "fill in plausible" numbers. If a source fails, record the exact error in
  `BLOCKERS.md` (append a section; do not delete others' sections) and use the best real alternative. Mock data only
  in `web/mock/`, and the app must show a "MOCK DATA" banner whenever it uses it.
- **No credentials.** SMAP/ECOSTRESS/GRACE/IMERG-from-GES-DISC need Earthdata: code paths may exist behind an env var
  (`EARTHDATA_TOKEN` / `~/.netrc`) but must not be required.
- **No personal info in requests.** HTTP User-Agent: `field-to-faucet-hackathon`.
- **Raw downloads** go to `data/raw/<source>/` (gitignored). Processed outputs in `data/processed/` must stay small
  (each file < 5 MB; parquet with zstd). Web JSON in `web/data/` (total < 15 MB; round floats to 3-4 significant digits).
- **Do not git commit or push.** The orchestrator commits. Do not edit files owned by another module.
- Every script is re-runnable (`python3 pipeline/<script>.py`), caches raw downloads, prints a short report.
- Each module documents its outputs in `notes/<module>.md`: columns, units, provenance URL, row counts, sanity stats,
  caveats, deviations from this contract.

## Network (verified reachable from this container on 2026-11-14)
waterservices.usgs.gov (NWIS dv/iv), api.waterdata.usgs.gov, planetarycomputer.microsoft.com (+ blobs hls2euwest,
modiseuwest, landcoverdata, soils, nasademeuwest, ai4edataeuwest .blob.core.windows.net), power.larc.nasa.gov,
hydro.nationalmap.gov (WBD + NHD MapServers), sdmdataaccess.sc.egov.usda.gov, www.nass.usda.gov (CDL national zips
2022-2025 exist: `https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip`,
1.7-2.1 GB each, supports HTTP range requests), cmr.earthdata.nasa.gov (search only), www2.census.gov, prd-tnm.s3.amazonaws.com.
Package registries (pypi, npm) work. Everything else is blocked by the proxy (403 on CONNECT) — log it in BLOCKERS.md.
Known facts: PC `hls2-l30`/`hls2-s30` start 2020-01-01 (no HLS 2016-2019 on PC). PC `usda-cdl` ends 2021. PC `gpm-imerg-hhr`
ends 2021-05-31 and each Zarr chunk is ~55 MB of global data (12 half-hours), so full daily IMERG is infeasible.
CropScape (nassgeodata.gmu.edu) does not respond. NWIS dv for 05484500 param 99133 works (2025-06-01 = 12.7 mg/L).

## Geography
- Sites: Raccoon River at Van Meter `05484500` (primary, basin id `raccoon`), Des Moines River at 2nd Ave, Des Moines
  `05482000` (secondary, basin id `desmoines`). Nitrate+nitrite param `99133` (mg/L as N); discharge `00060` (cfs).
- Basins = the land draining to each gauge, built from WBD HUC-12s by walking the `tohuc` network upstream from the
  gauge's HUC-12 (drop HUC-12s downstream of the gauge). The Des Moines basin extends into Minnesota; that is fine.
  The Des Moines River gauge is below Saylorville Reservoir — note the reservoir lag in caveats.
- CRS: store geometry as EPSG:4326 in web files; compute areas in EPSG:5070.
- Focus area for field drill-down: a contiguous set of ~6-15 HUC-12s (~400-1,200 km²) inside the Raccoon basin,
  entirely inside ONE HLS MGRS tile (prefer 15TUG or 15TVG), chosen for high row-crop share. ID list goes in
  `data/processed/focus_area.json` ({huc12s:[...], hls_tile, bbox_lonlat, reason}).

## Processed data files (owner module in brackets)
| File | Key | Columns / content |
|---|---|---|
| data/processed/nwis_daily.parquet [hydro] | site,date | site(str), date(date), no3_mgL (daily mean 99133), no3_qual, q_cfs (daily mean 00060), q_qual, load_kgN_day (= no3_mgL*q_cfs*2.4466), 2015-10-01..latest. If dv nitrate is missing for recent days, aggregate IV (15-min) to daily and flag `src='iv'` |
| data/processed/huc12.parquet [hydro] | huc12 | huc12, name, tohuc, basin ('raccoon'/'desmoines'), area_km2, geometry (WKB, EPSG:4326), in_focus (bool) |
| data/processed/power_daily_basin.parquet [hydro] | basin,date | T2M, T2M_MAX, T2M_MIN, PRECTOTCORR (mm), GWETROOT, GWETTOP, SNODP (cm), PRECSNOLAND (mm), area-weighted over POWER cells in basin, 2015-01-01..latest |
| data/processed/power_daily_cells.parquet [hydro] | cell_id,date | same vars per POWER cell (0.5° lat × 0.625° lon MERRA-2 grid) covering both basins |
| data/processed/power_cells.parquet [hydro] | cell_id | cell_id, lat, lon, weight per basin; mapping huc12→cell_id in `huc12_cell.parquet` |
| data/processed/imerg_sample.parquet [storms] | basin,date | imerg_mm (basin-mean daily total), imerg_max30_mmhr, power_mm, sampled-day rationale; 2016-2021 only |
| data/processed/cdl_basin_year.parquet [cover] | basin,year | shares of basin area: corn, soy, row_crop (corn+soy+other row), small_grain, hay, grass_pasture, forest, developed, water_wetland; cropland_km2. 2016-2025 |
| data/processed/cdl_huc12_year.parquet [cover] | huc12,year | same shares per HUC-12 |
| data/processed/cover_basin_8day.parquet [cover] | basin,date | MODIS 13Q1 Terra+Aqua (8-day effective) over row-crop pixels (CDL that year): n_valid, valid_frac, living_share, bare_share, snow_share, mean_ndvi, 2015-07..latest |
| data/processed/cover_basin_daily.parquet [cover] | basin,date | living_share, bare_share daily (time-interpolated; flag `filled` where gap > 24 days) |
| data/processed/cover_huc12_8day.parquet [cover] | huc12,date | living_share, bare_share, valid_frac (MODIS) |
| data/processed/soils_huc12.parquet [cover] | huc12 | poorly_drained_share (SSURGO drainage class poorly + very poorly, of row-crop area), somewhat_poorly_share, mean_slope_pct (NASADEM, row-crop), hydgrp_D_share |
| data/processed/focus_area.json [fields] | | see Geography |
| data/processed/fields.parquet [fields] | field_id | field_id ('F'+5 digits), lon, lat, x5070, y5070, huc12, area_ha, crop letters cdl_2016..cdl_2025 (C,S,W,O,H,P,R,X as in shared notes/cdl.md), crop_seq, drainagecl, poorly_drained (bool), slope_pct, power_cell_id, polygon (list of lon/lat ring) |
| data/processed/hls_field_ts.parquet [fields] | field_id,date | sensor, ndvi, ndti, gcvi, clear (bool) |
| data/processed/field_year.parquet [fields] | field_id,year | crop, winter_cover_score (0-1), winter_cover (bool), bare_days_total, bare_days_aprjun, bare_days_octdec, green_up_doy, n_clear_obs |
| data/processed/field_month.parquet [fields] | field_id,year,month | living_frac, bare_frac, n_obs (HLS) |
| data/processed/hls_vs_modis.json [fields] | | agreement of HLS living share vs MODIS living share in focus HUC-12s (r, bias, n) |

"Field" = a 400 m × 400 m cell (16 ha ≈ 40 acres, the Iowa quarter-quarter-section scale) on a regular EPSG:5070 grid,
kept when ≥ 80% of its CDL pixels are one row crop in ≥ 7 of the years 2016-2025. Render as squares on the map.
Living cover: NDVI ≥ 0.30 on a clear, snow-free observation (document and test sensitivity at 0.25/0.35).
Bare: NDVI < 0.30 (residue vs bare via NDTI is optional detail).

## Model outputs (phase 2; owners: model, scenario)
| File | Content |
|---|---|
| model/out/river_daily.parquet | site,date,obs,q_cfs,p10,p50,p90 (driver-only simulation), split ('train'/'test'/'live') |
| model/out/metrics.json | per site, per split, per model (gbm, reservoir, climatology, persistence_7d, persistence_14d): NSE, KGE, RMSE, MAE, bias, coverage80, exceedance-day hit rate/false alarm/CSI at 10 mg/L; 2025 crisis summary |
| model/out/sensitivity.json | learned d(nitrate)/d(bare_share) etc. with uncertainty |
| model/out/scenarios.json | see web/data/scenarios.json |
| model/out/field_scores.parquet | field_id, leak_index, leak_lbN_ac_yr p10/p50/p90 (calibrated so basin sum ≈ river load), monthly leak calendar |

## Web data contract (static app in `web/`, reads `web/data/*.json`, no build step)
- `meta.json`: {generated_at, data_through:{nwis, power, modis, hls, cdl}, sources:[{name, nasa:bool, role, url}], caveats:[...]}
- `basins.geojson` (2 features: basin, name, area_km2, gauge site), `huc12.geojson` (props: huc12, name, basin,
  area_km2, row_crop_share, poorly_drained_share, bare_days_wet (spring/fall bare+wet days, latest 3 yrs), leak_index,
  share_of_basin_leak, rank, in_focus), `rivers.geojson` (major NHD flowlines, simplified, props: name, order),
  `sites.json` [{site, name, lon, lat, role}], `places.json` [{name, lon, lat}] (Des Moines, intakes, towns in focus area).
- `river_series.json`: {mcl:10, split:{train:[start,end], test:[start,end], live:[start,end]},
  sites:{<site>:{name, dates:[], obs:[], q_cfs:[], p10:[], p50:[], p90:[]}}}  (daily, 2016-01-01..latest; null for gaps)
- `validation.json`: metrics.json reshaped for display + plain-language lines.
- `scenarios.json`: {adoption_levels:[0,5,...,50], method:"...", priors:[{name, effect, range, source}],
  by_year:{<year>:{site, observed:{days_over10, plant_days, ban_days}, levels:[{x, days_over10:{p50,lo,hi},
  plant_days:{...}, cost_usd:{...}, ban_days:{...}, load_tN:{...}, lbN_kept:{...}}]}},
  replay:{year:2025, site, dates:[], obs:[], base_p50:[], by_level:{<x>:[p50 daily]}}, thresholds:{plant_on_mgL, ban_mgL, cost_per_plant_day:{lo,hi}, source}}
- `outlook.json`: {issued, site, last_obs:{date, value}, dates:[], p10:[], p50:[], p90:[], prob_over10:[],
  drivers:{rain_7d_mm, rain_7d_pctile, gwetroot, gwetroot_pctile, bare_share, bare_share_pctile}, text}
- `fields.geojson`: focus-area fields as polygons, props: field_id, huc12, seq, leak_index, leak_pctile, drainage, slope_pct
- `field_detail.json`: {<field_id>:{seq, crop_2025, drainage, slope_pct, leak:{lbN_ac_yr:{p10,p50,p90}},
  calendar:{months:[1..12], bare_frac:[], rain_mm:[], storm_days:[], wetness:[], leak_risk:[]}, ndvi_recent:{dates:[], ndvi:[]},
  cover_years:{<year>: bool}, strategies:{<S0..S3>:{lbN_kept_ac:{p10,p50,p90}, fert_value_usd_ac:{...}}}}}
  (if too big, split into `field_detail/<huc12>.json`)
- `strategies.json`: {strategies:[{id:"S0".."S3", name, short, why, evidence:[{text, source, url}], satellite_evidence,
  n_loss_reduction:{mean, lo, hi, source}, yield_risk, soil_health:[..], gaps:[..], risks_local_review:[..],
  who_pays:[{program, detail, url}], cost_usd_ac:{lo,hi,source}}], disclaimer}
  S0 = current corn-soy (no cover), S1 = cereal rye before soybean, S2 = extended rotation (corn-soy-oats/alfalfa or
  small grain + clover), S3 = one more evidence-backed option (e.g. N-rate/timing: split/in-season N, or saturated buffer /
  bioreactor / prairie strips — pick one with Iowa evidence).

## Units & constants
- 1 cfs·mg/L = 2.4466 kg/day. lb = 0.453592 kg. acre = 0.404686 ha.
- EPA MCL nitrate-N = 10 mg/L.
- Impact numbers (plant days, $, ban days, people served, fertilizer price) come from `docs/facts.json` (facts module),
  each with source URL and verification status; never hard-code an unverified number.
