# Drought Bill: build contracts (every agent reads this first)

Spec: `docs/concepts/drought-bill.md`. Rules: `docs/BUILD_RULES.md`. Data access: `docs/DATA_ACCESS.md`.
App root: `apps/drought-bill/` (all paths below are relative to it).
Python: `/home/user/venv-db/bin/python` (numpy, pandas, pyarrow, scipy, scikit-learn, statsmodels, lightgbm, econml,
rasterio, pystac-client, planetary-computer, xarray, zarr, h5netcdf, netCDF4, fsspec, adlfs, geopandas, shapely, pyproj,
requests, openpyxl). Install more with `/home/user/venv-db/bin/python -m pip install <pkg>`.
Machine: 4 cores, 15 GB RAM, ~30 GB free disk. Other agents run at the same time, so use at most 6-8 download threads.

## Region
States (FIPS): IA 19, NE 31, KS 20, MO 29, IL 17, SD 46, MN 27. County key everywhere: `fips` = 5-char zero-padded
string (state 2 + county 3), e.g. "19149". Crops: `corn`, `soybeans`, `wheat` (all wheat), `sorghum`, plus `all` where a
row sums every crop. Focus county for field drill-down: **Plymouth County, Iowa (fips 19149)**.

## Network (this session's environment allows only these hosts)
pubfs-rma.fpac.usda.gov, www.rma.usda.gov, rma.usda.gov, power.larc.nasa.gov, planetarycomputer.microsoft.com,
www.nass.usda.gov, www2.census.gov, usdmdataservices.unl.edu, droughtmonitor.unl.edu, sdmdataaccess.sc.egov.usda.gov,
nassgeodata.gmu.edu, modiseuwest.blob.core.windows.net (MODIS COGs), nasagddp.blob.core.windows.net (NEX-GDDP-CMIP6),
cpdataeuwest.blob.core.windows.net, ai4edataeuwest.blob.core.windows.net, landcoverdata.blob.core.windows.net (CDL COGs),
cdn.jsdelivr.net, www.ewg.org, www.fb.org, www.ers.usda.gov, plus PyPI/npm.
NOT reachable: soils.blob.core.windows.net (gNATSGO rasters/tables on PC) -> use Soil Data Access SQL instead;
the IMERG Zarr storage account -> use NASA POWER precipitation and record IMERG in BLOCKERS.md; Earthdata (SMAP, ECOSTRESS).
If a request returns 403 from the proxy, the host is not allowed: write it into `notes/blockers_<module>.md`, do not retry forever.

## Hard rules
- Real data only. Never fabricate or "fill in" a number. Missing = null/NaN plus a note in `notes/<module>.md`.
- Cache raw downloads under `data/raw/<source>/` (gitignored). Scripts must be re-runnable and skip cached files.
- Write only your own module's files: `pipeline/<module>_*.py`, the outputs listed for your module, `notes/<module>.md`,
  `notes/blockers_<module>.md`. Never edit another module's files or this contract.
- Do NOT run git commit/push. The coordinator commits.
- No personal data in external requests. Use User-Agent "drought-bill-hackathon".
- Every output file is documented in `notes/<module>.md`: columns, units, years covered, row counts, provenance URL, caveats.

## Processed data files (`data/processed/`, parquet unless noted)

### module `rma` (USDA RMA)
Sources: Cause of Loss with month `https://pubfs-rma.fpac.usda.gov/pub/Web_Data_Files/Summary_of_Business/cause_of_loss/colsom_YYYY.zip`
(1989-2026; record layout in COL_Summary_of_Business_with_Month_All_Years.pdf/.doc in that folder) and Summary of Business
`.../state_county_crop/sobcov_YYYY.zip` (layout in SOB_State_County_Crop_with_Coverage_Level_1989_Forward.pdf) and
`sobtpu_YYYY.zip` (type/practice/unit, for the irrigated share).
- `rma_county_year.parquet` key (fips, year, crop) for years 2001-2025 (note in docs if 2025 is incomplete):
  insured_acres (net reported acres), liability_usd, premium_usd, subsidy_usd, indem_total_usd, indem_drought_usd
  (cause = Drought), indem_heat_usd (Heat + Hot Wind), indem_excess_moist_usd, det_acres_drought,
  irrigated_insured_share (share of insured acres under an irrigated practice, from sobtpu; null if unavailable),
  lcr_drought = indem_drought_usd / liability_usd, drought_usd_per_ac = indem_drought_usd / insured_acres.
  Use commodity (crop) year. crop in {corn, soybeans, wheat, sorghum, all}; `all` = every RMA commodity in the county.
- `rma_state_year.parquet`: same columns summed to state x year x crop, plus a `US` total row per year for all crops
  (used to cross-check the published 2022 national numbers: $19.1B total indemnity, $7.6B drought).

### module `geo` (NASS bulk, soils, county shapes)
- `counties.parquet`: fips, state_abbr, state_fips, name, lon, lat (interior point), land_km2. All counties in the 7 states.
- `web/data/counties.geojson`: the same counties, simplified (target < 1.5 MB), properties {fips, name, state}.
- `nass_county_year.parquet` key (fips, year, crop) 2000-2025: yield_bu_ac, planted_ac, harvested_ac (SURVEY, county level,
  crop in corn grain / soybeans / wheat all / sorghum grain; also `irrigated` / `non_irrigated` yield where NASS publishes it).
  Stream `qs.crops_YYYYMMDD.txt.gz` from https://www.nass.usda.gov/datasets/ (see shared/central_iowa_pipeline/pipeline/context_nass.py).
- `nass_prices.parquet` key (state_abbr, year, crop): price_received_usd_per_bu (marketing year, SURVEY, state or US level).
- `county_static.parquet` key fips: aws0_100_mm and aws0_150_mm (area-weighted available water storage from Soil Data Access
  `muaggatt` joined to `mapunit`/`legend`, weighted by muacres), irrigated_share (NASS Census of Agriculture 2017 and/or 2022:
  irrigated harvested cropland / harvested cropland; say which year), cropland_share if available, nccpi if available.

### module `cdl` (Cropland Data Layer via Planetary Computer, collection usda-cdl, items with usda_cdl:type = cropland)
- `cdl_county_year.parquet` key (fips, year) for window-end years 2012-2024 (5-year window y-4..y), also 2011 if 2007 is used:
  n_px (sampled cropland pixels), div_shannon_5y (mean per-pixel Shannon entropy of crop classes in the 5-year window),
  n_crops_5y (mean distinct crop classes per pixel in the window), share_cont_corn (corn in >= 3 consecutive years of the window),
  share_cs_only (only corn and soybean in the window, both present), share_3plus (>= 3 distinct crops), share_small_grain_5y
  (wheat/oats/barley/rye in at least one window year), share_perennial_5y (alfalfa/hay/grass), and that year's crop shares
  (corn_share, soy_share, wheat_share, sorghum_share, hay_alfalfa_share, other_share).
  Crop class grouping (from CDL codes) is documented in notes/cdl.md. Sampling is deterministic (same pixels every year).
- `cdl_county_static.parquet` key fips: the same metrics over the whole record 2008-2024 (17 years).
- `cdl_focus_fields.parquet` + `web/data/focus_fields.json` for Plymouth County IA (19149): >= 300 field samples (points inside
  homogeneous crop blocks), each with lon, lat, crop sequence 2008-2024 (one letter per year: C corn, S soy, W wheat, O other
  small grain, A alfalfa/hay, G sorghum, P pasture/grass, X other/non-crop), rotation_class (e.g. "corn-soy", "continuous corn",
  "3+ crop", "with perennial"), div_shannon_2020_2024, n_crops_2020_2024.
  focus_fields.json: {county:{fips,name}, years:[2008..2024], fields:[{id, lon, lat, seq, rotation_class, div5, ncrop5}]}.

### module `hazard` (NASA POWER + USDM)
- `hazard_county_year.parquet` key (fips, year) 1981-2025 (mark 2025 if partial): NASA POWER daily at each county's interior
  point (dedupe to POWER cells to save calls; record power_cell lon/lat). Parameters: T2M_MAX, T2M_MIN, PRECTOTCORR,
  GWETROOT, GWETTOP, RH2M or QV2M (for VPD), ALLSKY_SFC_SW_DWN optional. Columns:
  prcp_jja_mm, prcp_jul_mm (corn silking window Jul 1-31), prcp_aug_mm (soy pod fill), prcp_mjjas_mm,
  prcp_jja_anom_pct (vs 1991-2020 mean), spi_jja (standardized precipitation for JJA, gamma fit 1991-2020),
  edd30_jja (extreme degree days above 30 C, daily min/max with single sine interpolation, Jun-Aug),
  gdd10_30_mjjas, tmax_jja_c, vpd_jja_kpa, gwetroot_jja (mean), gwetroot_jul_aug (mean), gwetroot_jja_pct (percentile vs 1991-2020),
  hazard_z (a documented composite: mean of z-scores of -spi_jja, edd30_jja, -gwetroot_jja; z-scores vs 1991-2020 per county).
- `usdm_county_year.parquet` key (fips, year) 2000-2025: dsci_jja_mean (Drought Severity and Coverage Index, weekly, mean over
  Jun-Aug), d2plus_pct_jja_max, d3plus_pct_jja_max, weeks_d2plus_jja. API: https://usdmdataservices.unl.edu/api/ (county statistics).

### module `sat` (MODIS + NEX-GDDP-CMIP6)
- `modis_county_year.parquet` key (fips, year) 2001-2025: ndvi_jul_aug (mean of MOD13Q1 16-day NDVI composites with
  compositing start dates in Jul-Aug, read from PC modis-13Q1-061 COGs at a coarse overview, masked to cropland using the CDL
  2016-ish crop mask if available, else all land, state which), vci_jul_aug (Vegetation Condition Index 0-100 per county vs its
  2001-2024 min/max), ndvi_z (z vs 2001-2024), plus n_px. Tiles needed roughly h09v04, h09v05, h10v04, h10v05, h11v04, h11v05.
- `cmip6_deltas.parquet` key (fips, gcm, scenario): NEX-GDDP-CMIP6 (PC nasa-nex-gddp-cmip6) changes 2035-2054 vs 1995-2014 in
  the same variables used by the hazard model: d_prcp_jja_pct, d_edd30_jja (from tasmax/tasmin), d_tmax_jja_c, d_vpd_jja (if hurs
  available). >= 5 GCMs if time allows (at least 3), scenarios ssp245 and ssp585. Counties may share the 0.25 deg cell nearest
  their interior point. Reuse/adapt shared/central_iowa_pipeline/pipeline/context_climate.py. Subsample years if needed and say so.

## Model and web outputs (module `model`, after the data lands)
- `model/` holds the scripts and `model/outputs/*.json`. The strategy engine writes the web files below.
- Loss target: drought loss cost ratio `lcr_drought` (price-normalized), converted to $/acre with each county's recent
  (2020-2024 mean) liability per insured acre. Also report $/acre directly.
- Train through 2020; test 2021-2024 with 2022 and 2023 as headline drought years. Baselines: county mean loss cost, hazard-only model.

## Web data contract (`web/data/*.json`, read by the static app)
- `meta.json`: {generated_at, region:{states:[...]}, data_sources:[{name, nasa:bool, role, url}], caveats:[...], mock:false}
- `counties.geojson` (geo module).
- `county_bill.json`: {units:"USD per insured acre per year", dollar_year:"nominal|2024", counties:{<fips>:{name, state,
    insured_acres, liab_per_ac, subsidy_share, expected_bill:{est,lo,hi}, bill_1in5:{est,lo,hi}, bill_1in10:{est,lo,hi},
    taxpayer_expected_bill:{est,lo,hi}, actual:{2012:x, 2022:x, 2023:x}, hindcast:{2022:{pred,lo,hi,actual}, 2023:{...}},
    bill_2045:{ssp245:{est,lo,hi}, ssp585:{est,lo,hi}}, diversity:{now, p90_region, n_crops_now, share_cont_corn},
    slider:{div_values:[...], bill_2022_style:[...], lo:[...], hi:[...]}, irrigated_share, aws_mm}}}
- `hindcast.json`: {train_years, test_years, metrics:{model:{mae, rmse, r2, spearman, total_bias_pct}, baseline_mean:{...},
    baseline_hazard_only:{...}}, by_year:{2022:{pred_total_usd, lo, hi, actual_total_usd}, 2023:{...}}, by_state:[...]}
- `strategies.json`: {strategies:[{id, name, short, description}], counties:{<fips>:{<rotation_class>:[{strategy_id,
    expected_bill:{est,lo,hi}, bill_1in10:{est,lo,hi}, delta_bill:{est,lo,hi}, delta_income_per_ac:{est,lo,hi},
    evidence:{grade:"strong|moderate|thin", sources:[...]}, why, benefits:[...], gaps:[...], risks:[...]}]}}}
- `regional_summary.json`: totals by state and region: expected annual drought bill $, taxpayer share $, 2022 actual $, 2045 change.
- `focus_fields.json` (cdl module).
