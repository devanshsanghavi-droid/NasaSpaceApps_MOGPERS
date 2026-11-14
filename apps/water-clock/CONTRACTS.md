# Water Clock build contract (read this first)

Spec: `docs/concepts/water-clock.md`. Rules: `docs/BUILD_RULES.md`. Everything for this concept lives under `apps/water-clock/`.
App root below = `apps/water-clock/`. Python: system `python3` (numpy, pandas, scipy, statsmodels, pyarrow, rasterio, xarray, zarr,
netCDF4, h5netcdf, geopandas, shapely, pyproj, pystac-client, planetary-computer, fsspec, aiohttp, matplotlib are installed;
`pip install <pkg>` for anything else). Machine: 4 CPUs, 15 GB RAM. Keep thread pools at <= 6 workers.

## Region
Western Kansas Groundwater Management Districts 1, 3 and 4 (GMD1, GMD3, GMD4). Working county list (Kansas FIPS 20xxx):
- GMD1: Greeley 071, Wichita 203, Scott 171, Lane 101
- GMD3: Hamilton 075, Kearny 093, Finney 055, Gray 069, Ford 057, Stanton 187, Grant 067, Haskell 081, Morton 129, Stevens 189, Seward 175, Meade 119
- GMD4: Cheyenne 023, Rawlins 153, Decatur 039, Sherman 181, Thomas 193, Sheridan 179, Wallace 199, Logan 109, Gove 063, Graham 065
Counties straddling a GMD edge are assigned to the GMD covering most of their irrigated area. Use official GMD polygons from KGS if
they can be fetched (record the source); otherwise this county list is the region definition. Bounding box ~ [-102.06, 36.99, -99.55, 40.01].

## Network facts (verified 2026-11-14 in this container)
Reachable (HTTPS via the session proxy): www.kgs.ku.edu, geohydro.kgs.ku.edu (WIZARD at /geohydro/wizard/, WIMAS at /geohydro/wimas/),
data.kgs.ku.edu, nasagrace.unl.edu (GRACE-DA weekly folders `/data/YYYYMMDD/` with `GRACEDADM_CLSM0125US_7D.AYYYYMMDD.030.nc4` =
groundwater/root-zone/surface soil-moisture PERCENTILES, 0.125 deg CONUS, 2002-04..2026-11), gravis.gfz.de and isdc-data.gfz.de
(GFZ GRACE/GRACE-FO, no login), power.larc.nasa.gov, planetarycomputer.microsoft.com plus blob hosts hls2euwest, landcoverdata (CDL),
ai4edataeuwest (IMERG zarr, gridmet), modiseuwest, nasagddp (NEX-GDDP-CMIP6), cpdataeuwest (terraclimate), soils, nasademeuwest
(.blob.core.windows.net), waterservices.usgs.gov and api.waterdata.usgs.gov (NWIS groundwater levels), www.nass.usda.gov (QuickStats bulk
files under /datasets/), www2.census.gov, www.sciencebase.gov and prod-is-usgs-sb-prod-content.s3.amazonaws.com (USGS data releases),
www.ers.usda.gov, ds.nccs.nasa.gov.
BLOCKED: hercules.kgs.ku.edu, abyss.kgs.ku.edu, chasm.kgs.ku.edu, quickstats.nass.usda.gov (API, needs key anyway), podaac / urs.earthdata
(no Earthdata login), grace.jpl.nasa.gov, www.ncei.noaa.gov, mymarketnews.ams.usda.gov. download.csr.utexas.edu (CSR mascons) connects
but fails TLS verification (its emSign root CA is not in the trust store) - never disable TLS verification; record it as a blocker.
Any other host will be refused with a 403 from the proxy. Do not retry refused hosts; write them into notes and BLOCKERS.
Use User-Agent "water-clock-hackathon" for all requests. Never put personal info in requests.

## Directory layout
- `pipeline/<module>_*.py` data fetch/processing scripts, re-runnable, caching raw downloads in `data/raw/<source>/` (gitignored).
- `data/processed/` small processed outputs (parquet/json, each <= ~5 MB) that ARE committed.
- `model/*.py` groundwater state model, validation, rotation engine. `model/run_all.py` regenerates every `web/data/*.json`.
- `web/` static app (index.html, js/, css, data/*.json). No build step. CDN libs pinned (e.g. maplibre-gl@4.7.1, chart.js@4.4.4).
- `notes/<module>.md` per module: what was fetched, from where (exact URL), columns + units, coverage, caveats, failures.
- Docs at app root: README.md, PITCH.md, VALIDATION.md, CLAIMS.md, BLOCKERS.md.

## Processed data files (owner module in brackets). Units: feet, acre-feet (AF), inches, USD, years.
| File | Owner | Key | Columns |
|---|---|---|---|
| data/processed/wells_levels.parquet | wells | well_id, meas_date | source ("KGS_WIZARD"/"USGS_NWIS"), year (water year: winter measurement Dec-Mar assigned to the Jan year), depth_to_water_ft, wl_elev_ft (water-level elevation, ft NAVD88/NGVD as given), measurement_method/status if any |
| data/processed/wells_meta.parquet | wells | well_id | source, source_id, lon, lat, county_fips (5-char), gmd, land_elev_ft, well_depth_ft, base_elev_ft (aquifer base/bedrock elevation at well from KGS/USGS surface), n_years, first_year, last_year |
| data/processed/aquifer_base.json or .tif-derived grid | wells | - | aquifer base elevation (ft) on a regular grid covering the region + source URL; and KGS/USGS published saturated thickness for at least one year if obtainable (for cross-check) |
| data/processed/wimas_use.parquet | pumping | pdiv_id, year | wr_file_no, lon, lat, county_fips, gmd, use ("IRR" etc.), af_reported, acres_irrigated, crop codes/names if given, authorized_af, sec/twn/rng if given |
| data/processed/grace_region.parquet | nasa | date | gws_pct, rtzsm_pct, sfsm_pct (GRACE-DA percentiles, region mean), tws_cm (GFZ/other volumetric GRACE TWS anomaly region mean, if obtained), source |
| data/processed/grace_maps.json | nasa | - | per-cell grids for the map: {cell_deg, bbox, dates:[...], gws_pct:[[...]], tws_trend_cm_yr (if volumetric available)} small |
| data/processed/power_county_annual.parquet | nasa | county_fips, year | precip_in (annual), precip_gs_in (Apr-Sep), et0_in (FAO-56 PM from POWER daily, annual), et0_gs_in, tmax_jja_f; 1984-2025 (complete years) |
| data/processed/imerg_county_annual.parquet | nasa | county_fips, year | imerg_precip_in, imerg_precip_gs_in (2001-2024 or what is feasible; if too slow, a region-mean series is acceptable) |
| data/processed/modis_et_county.parquet | nasa | county_fips, year | modis_et_in (MOD16A3GF annual ET), optionally by CDL crop class (irrigated-corn pixels vs dryland-wheat pixels) |
| data/processed/cdl_county.parquet | nasa | county_fips, year, crop | acres (CDL pixel count * 0.2224 ac), 2008-2024 at least; crops: corn, sorghum, winter wheat, soybeans, cotton, alfalfa, fallow/idle, grass/pasture |
| data/processed/cdl_points.parquet | nasa | pdiv_id, year | CDL crop code at each WIMAS point of diversion (or its quarter-section centroid) 2008-2024 |
| data/processed/hls_irrigation.parquet | nasa | sample_id, year | for a focus county: HLS NDVI during a mid-summer dry spell (IMERG/POWER-identified) at sample points; irrigated flag; compare against WIMAS irrigated points (accuracy) |
| data/processed/cmip6_2045.json | nasa | - | NEX-GDDP-CMIP6 for region centroid cells: >=3 GCMs x {ssp245, ssp585}: change 1995-2014 -> 2035-2055 in pr (in/yr, Apr-Sep), tasmax JJA (F), and an ET0 change (Hargreaves or PM from available vars, %) |
| data/processed/nass_county.parquet | econ | county_fips, year, crop, practice | yield (bu/ac or lb/ac), harvested_acres; practice in {IRRIGATED, NON-IRRIGATED, ALL}; corn, sorghum, wheat, soybeans, cotton; 2000-2024 |
| data/processed/prices.parquet | econ | year, crop | Kansas price received (USD/bu or /lb) from NASS bulk (or AMS if reachable), 2010-2025 |
| data/processed/costs.json | econ | - | per crop & practice operating + ownership cost per acre (USD) with source (ERS Commodity Costs and Returns, region Prairie Gateway / Heartland, or KSU Farm Management Guides), year |
| data/processed/counties.geojson | econ | fips | simplified county polygons for the region (+ name, gmd); plus gmd.geojson if official GMD polygons found |
| data/processed/county_context.json | econ | fips | population (Census), main towns, and any share-of-economy-from-irrigated-ag figure WITH SOURCE (else null) |

## Model outputs (owner: model) - the web contract, all in web/data/
- `meta.json`: {generated_at, region, data_sources:[{name, nasa:bool, role, url, status:"used"|"blocked"|"partial"}], caveats:[...]}
- `counties.geojson`: region counties with properties {fips, name, gmd, years_p10, years_p50, years_p90 (at the default 30 ft threshold)}
- `county_clocks.json`: {threshold_default_ft:30, thresholds_ft:[15,30,50], counties:[{fips, name, gmd, sat_thick_ft:{p10,p50,p90}, decline_ft_yr:{est,lo,hi}, years_left:{"15":{p10,p50,p90},"30":{...},"50":{...}}, irrigated_acres, pumping_af_yr, corn_share_irrigated, n_wells, data_quality:"good|fair|thin", town_note}], gmds:[same shape aggregated]}
- `fields.json`: farmer-clickable points = WIMAS irrigation points of diversion (subsample <= ~6000 if needed, documented): {columns:["id","lon","lat","fips","acres","crop","af_yr","sat_ft","decl","y10","y50","y90"], rows:[...]} (years at 30 ft threshold; sat_ft and decl at that location from the state model)
- `grid.json`: years-left (p50, 30 ft) and saturated thickness on a regular grid for map coloring {cell_deg, rows:[[lon,lat,sat_ft,decl_ft_yr,years_p50]]}
- `strategies.json`: {strategies:[{id:"S0".."S3+", name, short, rotation:[crops], irrigation:"full|limited|none", why, evidence:[{text, source, url}], benefits:[...], gaps:[...], risks:[...], soil_health:"...", water_in_ac:{est,lo,hi}, pumping_change_pct:{est,lo,hi} (vs S0), income_usd_ac:{est,lo,hi}, yield_risk:"...", applies_where:"..."}], per_county:{fips:{S0:{net_pumping_in_ac, income_usd_ac}, ...}}, method:"..."}
- `scenario.json`: everything the client needs to compute "if X% of irrigated corn shifts to strategy Y, county clock gains Z years" without the server: per county {sat_avail_ft (above threshold, per threshold), decline_ft_yr, decline_from_pumping_ft_yr (pumping-attributable part), irrigated_corn_acres, irrigated_acres, pumping_af_yr, sy, ft_per_af_ac (response coefficient)}, plus the formula as text.
- `grace.json`: {series:{dates, gws_pct, tws_cm|null}, maps:{...}, wells_vs_grace:{well_storage_anom_series, correlation, trend_wells_cm_yr, trend_grace_cm_yr, notes}}
- `validation.json`: hindcast results (see model section), plus GRACE-vs-wells comparison numbers.
- `climate.json`: 2045 shift: {per scenario: et0_change_pct, gs_precip_change_in, extra_pumping_in_ac, clock_shift_years (region/county)}

## Model requirements (owner: model)
- State model per location: water-level elevation h(t) with local-linear-trend state-space / hierarchical Bayesian decline rates
  (wells partially pooled toward their county/GMD mean), interpolated to the grid and to fields (kriging/GP or inverse-distance with
  uncertainty). Saturated thickness = h - aquifer base. Water-balance link: dh/dt = (R - Q_net/A)/Sy with Sy prior (KGS ~0.15, range 0.10-0.20)
  and recharge prior (literature range for western KS, e.g. 0.1-1.5 in/yr) -> draws give uncertainty bands. GRACE is the regional constraint:
  if volumetric TWS is available, compare/fuse regional storage-change rate (Sy * dh/dt aggregated) with GRACE trend; if only GRACE-DA
  percentiles, use them as an independent consistency check (correlation and sign of trend) and say so plainly.
- Years left = (sat_thick - threshold) / decline_rate, with Monte Carlo over decline-rate posterior, Sy, recharge; report p10/p50/p90 and
  thresholds 15/30/50 ft. Locations with rising or flat water levels -> ">100 years" (cap 100, flagged), never negative.
- Validation (VALIDATION.md + validation.json): out-of-time hindcast - fit on data through 2014, predict 2015-2024 (or latest) water levels
  for held-out wells (spatial holdout: e.g. 20% of wells by county-stratified random split, and well-level temporal holdout);
  metrics: MAE/RMSE of predicted 10-yr decline (ft) and of predicted 2024 water level; 80% interval coverage; baselines: (a) no-change,
  (b) each well's own linear trend (for temporal holdout), (c) county-mean trend. Plus GRACE vs aggregated well storage: correlation,
  trend comparison.
- Rotation engine: net pumping per crop = irrigation requirement = (crop ET - effective precip) / irrigation efficiency, calibrated against
  WIMAS reported AF per acre by crop where WIMAS has crop info; years gained = sat_avail / new_decline - sat_avail / old_decline where the
  pumping-attributable part of decline scales with net withdrawal; income per acre = NASS county yield (irrigated vs dryland) x KS price -
  cost per acre (with ranges from yield and price variability). 2045 shift from cmip6_2045.json (ET0 and precip changes -> irrigation
  requirement change -> decline change -> clock shift).

## Rules for every agent
- Real data only. If a source fails, write null + an explanation in notes/<module>.md and add a line to BLOCKERS.md (error, host, what would
  unblock it). Never fabricate or "fill in" numbers. Literature constants (e.g. Sy) must carry a citation.
- Write only your own module's files. Do not edit other modules' files or this contract (except appending to BLOCKERS.md).
- Git: commit only your own paths (`git add apps/water-clock/<your paths>`), never `git add -A`. If `.git/index.lock` exists, wait a few
  seconds and retry. Push with `git push -u origin water-clock` (retry on network error). Never touch other branches. Commit messages end with:
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LVZuX7TnteGzg9XK4avuZb
