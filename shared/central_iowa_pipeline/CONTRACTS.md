# COUNTERFIELD build contracts (read this first)

Project root: this folder. Python: `.venv/bin/python` (packages: rasterio, pystac-client, planetary-computer, xarray, zarr, cftime,
numpy, pandas, pyarrow, scipy, scikit-learn, econml, lightgbm, statsmodels, geopandas, shapely, h5py, h5netcdf, netCDF4, requests).
Install anything else with `.venv/bin/python -m pip install <pkg>` (never `.venv/bin/pip`, its shebang is broken).
Design doc: `../COUNTERFIELD_design.md`. Region + grid: `data/region.json`.

## Data access facts (verified)
- Microsoft Planetary Computer STAC (no login): `pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=planetary_computer.sign_inplace)`.
  Collections: hls2-l30, hls2-s30 (bands B02..B12, B8A, Fmask; COG 3660x3660 30 m, overviews 2/4/8/16; reading a band at overview 2 (60 m) takes ~5-8 s),
  usda-cdl (filter `query={"usda_cdl:type":{"eq":"cropland"}}`, EPSG:5070 30 m), gnatsgo-rasters (mukey, aws0_100, soc0_30, nccpi3corn, nccpi3soy, droughty, rootznaws ...; 10 m Albers),
  nasadem (elevation, 1 arcsec), gpm-imerg-hhr (Zarr; open with use_cftime=True; variable `precipitationCal`), modis-13Q1-061, modis-16A3GF-061, nasa-nex-gddp-cmip6, era5-pds, daymet, gridmet, terraclimate.
  PC SAS tokens expire (~24 h); re-sign items if reads start failing with 403.
- NASA POWER daily API works: https://power.larc.nasa.gov/api/temporal/daily/point?parameters=...&community=AG&longitude=..&latitude=..&start=YYYYMMDD&end=YYYYMMDD&format=JSON
- USDA Soil Data Access works: POST https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest data={"query": SQL, "format":"JSON+COLUMNNAME"}
- NO Earthdata login available: SMAP, ECOSTRESS, GRACE, NLDAS direct downloads are not possible right now. Write code paths for them behind a flag
  (earthaccess + ~/.netrc) but do not depend on them. Never ask for or handle credentials.
- Network fetches from modis.ornl.gov and open-meteo time out. Use PC instead.
- Run long jobs with concurrency (ThreadPoolExecutor, 8-12 workers; machine has 12 cores, ~50 GB disk free). Cache raw downloads in `data/raw/<source>/` so re-runs are cheap.

## Unit of analysis
"Field sample" = a grid point (480 m spacing, see region.json) that sits inside a homogeneous crop block. Every dataset is keyed by `field_id`
('f' + 5-digit grid_id) and, where annual, by `year`. The 50,850 grid points are the universe; `data/fields.parquet` decides which are fields.

## Files each module must produce (parquet unless noted; documented in notes/<module>.md with columns, units, provenance, caveats)
| File | Owner | Key | Content |
|---|---|---|---|
| data/fields.parquet | cdl | field_id | grid_id,row,col,x,y,lon,lat,county_fips,county_name, cdl_2008..cdl_2024 (int codes, center pixel), homog_YYYY (share of 3x3 CDL block equal to center), is_field (bool: corn/soy/other-row-crop in >=7 of 9 years 2016-2024 and homogeneous), crop_seq_2016_2024 (string like 'CSCSCSCSC') |
| data/hls_ts.parquet | hls | field_id,date | sensor (L30/S30), doy, ndvi, ndti, gcvi, nbr2/bsi as useful, fmask_clear (bool). ALL grid points. 60 m overview pixel at the point (or 2x2 mean) |
| data/confounders.parquet | conf | field_id | elev_m, slope_pct, curvature (profile, convex>0), twi, flowacc, mukey, aws0_100, soc0_30, nccpi3corn, nccpi3soy, droughty, rootznaws, kwfact, om_r, drainagecl, hydgrp, clay_pct, sand_pct, power_cell_id |
| data/weather_annual.parquet | conf | power_cell_id,year | 1981-2024 per NASA POWER 0.5 deg cell covering the tile: gdd_may_sep (base 10C cap 30C), hdd30_jul_aug (hours/degree-days >30C), prcp_amj, prcp_jja, prcp_annual, tmax_jul, vpd_jja (if derivable), gwetroot_apr (POWER root-zone wetness), frost_last_spring_doy, frost_first_fall_doy, imerg_max30min_amj / imerg_r_factor (if IMERG read succeeds; else null + note) |
| data/weather_daily_power.parquet | conf | power_cell_id,date | raw POWER daily for 1981-2024 (T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, RH2M, GWETROOT, GWETTOP, ALLSKY_SFC_SW_DWN) |
| data/nass_county_yields.parquet | context | county_fips,year,crop | NASS county yields (corn bu/ac, soybeans bu/ac) for all Iowa counties 2008-2024 |
| data/counties.geojson | context | fips | county polygons for counties intersecting the tile (simplified) |
| data/climate_future.json | context | - | NEX-GDDP-CMIP6 for the tile: >=3 GCMs x {ssp245, ssp585} x periods {1995-2014 historical, 2035-2055}: distributions (per-year values) of gdd_may_sep, hdd30_jul_aug (or days tmax>30C Jul-Aug), prcp_amj, prcp_jja, tmax_jul. Plus `analogs`: CONUS 0.25 deg cells (or counties) whose 1995-2014 climate best matches the tile's 2045 climate (top 25, with distance and lon/lat, state) |
| data/evidence_priors.json | evidence | - | randomized/long-term trial effect priors per strategy x outcome with mean, se/CI, n, source citation, URL, notes. Plus `citation_checks` for the 3 open claims |
| data/treatments.parquet | phase2 | field_id,year | crop, prev_crop, cover_crop (bool+score), tillage_class (from post-plant NDTI), bare_days, bare_days_erosive (Apr-Jun), green_up_doy, peak_gcvi |
| data/outcomes.parquet | phase2 | field_id,year | yield_proxy, yield_bu_ac (NASS-calibrated), yield_anom (vs field mean), erosion_index (RUSLE-style with measured cover + tillage term), drought_flag |
| model/*.json | phase2 | - | causal outputs; then exported to web/data per the web contract below |

## Web contract (static site in web/, reads web/data/*.json; no build step; CDN libs allowed: maplibre-gl, chart.js or d3, pinned versions)
- web/data/meta.json: {region, generated_at, data_sources:[{name, nasa:bool, role, url}], caveats:[...]}
- web/data/fields_index.json: {columns:["field_id","lon","lat","type_id","seq","badge_best","county"], rows:[[...],...]} (all is_field samples)
- web/data/field_types.json: {types:[{type_id, label (plain words, e.g. "Rolling, well-drained, high-productivity corn-soy"), definition:{...}, n_fields}]}
- web/data/effects.json: {strategies:[{strategy_id:"S0".."S3", name, short, description, applies_to:"..."}],
    by_type:{type_id:{strategy_id:{outcomes:{yield_pct:{est,lo,hi,measured:true}, erosion_t_ac:{...}, drought_loss_pct:{...}, n2o_pct:{...,measured:false}, nitrate_pct:{...,measured:false}},
    badge:"strong|moderate|thin|beyond", evidence:{n_twin_fields, n_trials, quasi_experiment:null|"...", estimators:{dr_learner:{est,lo,hi}, did:{...}, forest:{...}}, gamma:float, overlap:float},
    why:"...", gaps:["..."], risks:["..."], failure_box:"...", signpost:"...", next_step:"...", who_pays:["EQIP 340", ...],
    climate:{ssp245:{est,lo,hi,in_support:bool}, ssp585:{...}, analog_note:"..."}}}}}
- web/data/hero_fields.json: [{field_id, name, lon, lat, type_id, story, ribbon:{months:[1..12], bare_frac:[], erosivity:[], heat_risk:[]},
    synth_control:{years:[], actual:[], counterfactual:[], lo:[], hi:[], switch_year, outcome:"yield_bu_ac"}, twins:[field_id...]}]
- web/data/hindcast.json: {train_years, test_years, metrics:{causal:{kendall_tau, top1_regret, coverage}, rule_baseline:{...}, correlational_ml:{...}}, by_type:[...]}
- web/data/climate.json: {scenarios:{ssp245:{years:[...], gdd:[...], hdd30:[...], prcp_amj:[...]}, ssp585:{...}}, historical:{...}, analogs:[{lon,lat,state,label,distance}]}
- web/data/policy.json: {tree:[{node, rule, n, recommended, value_per_dollar}], value_vs_uniform:{est,lo,hi}}
- web/data/signpost.json: {variable, source, climatology_years, current_value, percentile, triggered:bool, message}
- web/data/badge_calibration.json: {badge:{empirical_error_rate, coverage, n}}

## Rules for every agent
- Real data only in data/ and model/. If something cannot be fetched, write null + an explanation in notes/<module>.md; never fabricate numbers.
- Write only inside your own module's files (pipeline/<module>_*.py, the data files you own, notes/<module>.md). Do not edit other modules' files or this contract.
- Every script must be re-runnable (`.venv/bin/python pipeline/<script>.py`) and cache raw downloads.
- Keep the user's identity out of any external request (no emails in User-Agent; use "counterfield-hackathon").
