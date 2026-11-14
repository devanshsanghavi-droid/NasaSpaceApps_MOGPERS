# nasa (part A): water & climate - GRACE, NASA POWER, GPM IMERG, NEX-GDDP-CMIP6

Owner files: `pipeline/nasa_common.py`, `pipeline/nasa_grace_da.py`, `pipeline/nasa_grace_gfz.py`, `pipeline/nasa_grace_maps.py`,
`pipeline/nasa_power.py`, `pipeline/nasa_imerg.py`, `pipeline/nasa_cmip6.py`; outputs in `data/processed/`:
`grace_region.parquet`, `grace_maps.json`, `power_county_annual.parquet`, `power_region_daily.parquet` (extra),
`imerg_county_annual.parquet`, `cmip6_2045.json`. Raw downloads are cached under `data/raw/{grace_da,gfz,power,imerg,cmip6,census}/` (gitignored).
Re-run order: `nasa_power.py` -> `nasa_grace_da.py` -> `nasa_grace_gfz.py` (optionally `WATER_CLOCK_TERRACLIMATE=1`) ->
`nasa_grace_maps.py` -> `nasa_imerg.py` -> `nasa_cmip6.py`. All data below are real downloads; nothing was typed in.

## Region definition used
26 counties (the CONTRACTS.md list: GMD1 4 + GMD3 12 + GMD4 10; the task text said 27, the contract lists 26). Polygons and
centroids from the Census cartographic boundary file https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip
(centroid = equal-area EPSG:5070 centroid). Region area 59,444 km2 (14.7 M acres). Official KGS GMD polygons were not used here.

## 1. GRACE

### 1a. GRACE-DA percentiles (nasagrace.unl.edu) -> `grace_region.parquet` columns gws_pct, rtzsm_pct, sfsm_pct
- Files: `https://nasagrace.unl.edu/data/YYYYMMDD/GRACEDADM_CLSM0125US_7D.AYYYYMMDD.030.nc4` (weekly list scraped from
  https://nasagrace.unl.edu/ConusData.aspx, 1,284 weekly dates 2002-04-01 .. 2026-11-09). Sampled the FIRST weekly file of each
  month: 296 months, 295 downloaded. **2025-10 is missing**: every October-2025 weekly folder tried returned HTTP 404
  (`/data/20251006/...` 404, the other Oct-2025 dates also failed); 2025-11-03 404 -> replaced by 2025-11-17.
- Variables are PERCENTILES (0-100) of the GRACE-DA Catchment model storage relative to its 1948-2012 climatology - a drought
  indicator, not a volume. Region mean = unweighted mean of the 384 0.125-deg cells whose centres fall inside the 26 counties;
  `gws_pct_gmd1/3/4` = same per GMD. `n_cells` = valid cells.
- Result: region gws percentile annual means: 2003 37.5, 2004 29.7, 2007 67.6, 2010 65.7, 2012 17.9, 2013 7.0, 2014 5.3,
  2019 53.8, 2022 7.4, 2023 3.6, 2024 4.6, 2025 7.6, 2026 (Jan-Nov) 5.6. Record low of the sample: 2.5 (2026-09-07); latest
  (2026-11-02) 8.3. GMD4 is the lowest in 2023-2026 (2.8-4.0).
- Caveat: GRACE-DA assimilates GRACE TWS into a land-surface model that has **no irrigation pumping**; the percentile is relative to a
  modelled climatology, so it mixes drought and depletion. Use it as an independent consistency check, not a storage volume.

### 1b. Volumetric GRACE/GRACE-FO TWS (no Earthdata login) -> `grace_region.parquet` columns tws_cm, tws_std_cm, g3p_*_cm
- **GFZ GravIS RL06 Level-3 TWS v0006** (Boergens, Dobslaw, Dill 2019, doi:10.5880/GFZ.GRAVIS_06_L3_TWS):
  https://isdc-data.gfz.de/grace/GravIS/GFZ/Level-3/TWS/GRAVIS-3_GFZOP_0600_TWS_GRID_GFZ_0006.nc (514 MB, 1-deg global,
  260 monthly solutions 2002-04 .. 2026-08, variable `tws` in cm EWH anomaly; `std_tws` uncertainty).
- **G3P v1.12** Global Gravity-based Groundwater Product (Guentner et al. 2024, doi:10.5880/G3P.2024.001):
  https://isdc-data.gfz.de/grace/GravIS/G3P/v1.12/G3P_v1.12.zip (1.2 GB zip; GWSA, RZSM, SWE, SWS, TWS members, 0.5 deg,
  2002-04 .. 2023-09). GWSA = GRACE TWS minus soil moisture, snow, surface water and glaciers -> a GRACE-based **groundwater**
  storage anomaly made by the GFZ team (better than our own subtraction).
- Region mean: area-weighted over cells (weight = km2 of the cell inside the 26 counties; 17 one-degree cells touch the region,
  12 carry >99% of the weight). GRACE's effective resolution is ~300 km, so this is a western-Kansas-scale signal with
  leakage from neighbours (incl. the Texas/Oklahoma panhandles, where the trend is stronger), not county-resolved.
- Month assignment: two GFZ solutions fall in Oct 2011 and in Apr 2015 (none in Nov 2011 / May 2015); the later one is moved
  to the empty next month. GFZ months are joined to the GRACE-DA row of the same calendar month (`month` column); 2025-10 is a
  GFZ-only row. The 2017-07..2018-05 GRACE/GRACE-FO gap and other missing months are left empty (no interpolation).
- Trend: OLS on monthly values with annual + semi-annual harmonics, gap months omitted, SE inflated for lag-1 residual
  autocorrelation (n_eff = n(1-r1)/(1+r1)).

| Series (region mean) | 2003-2016 cm/yr (SE) | 2003-latest cm/yr (SE) | 2018-latest (GRACE-FO) cm/yr (SE) |
|---|---|---|---|
| GFZ TWS (latest 2026-08) | -1.04 (0.32) | -0.89 (0.14) | -2.46 (0.39) |
| G3P groundwater GWSA (latest 2023-09) | -0.79 (0.32) | -0.57 (0.18) | -2.21 (1.26) |
| G3P root-zone soil moisture | -0.18 (0.24) | -0.13 (0.12) | -1.15 (0.99) |
| G3P TWS (COST-G) | -0.94 (0.70) | -0.68 (0.30) | -3.50 (0.74) |
| GFZ TWS minus TerraClimate soil moisture (latest 2021-12) | -1.06 (0.31) | -0.63 (0.19) | -1.71 (1.32) |

- In volume over the 59,444 km2 region: -0.89 cm/yr = -0.53 km3/yr (~0.43 million acre-feet/yr); 2003-2016 -1.04 cm/yr
  = ~0.50 MAF/yr; G3P groundwater -0.57 cm/yr = ~0.27 MAF/yr. Annual-mean GFZ TWS anomaly: 2003 +5.1 cm, 2012 -5.7, 2014 -9.2,
  2019 +0.3, 2023 -15.1, 2024 -13.5, 2025 -14.4, 2026 (Jan-Aug) -19.1; latest month 2026-08 -25.3 cm. These are
  "water seen from space" numbers for western Kansas at GRACE scale; for comparison, the NASA/JPL PIA16840 statement is
  ~2.5 cm/yr for the *southern* High Plains 2003-2012 (stronger depletion zone south of our region; the per-cell map shows
  -1.5 to -2 cm/yr over the Texas panhandle vs -0.3 to -1.5 cm/yr over our cells).
- Correlations of the monthly region series: GRACE-DA gws_pct vs GFZ TWS r = 0.81; GFZ TWS vs G3P GWSA r = 0.89;
  gws_pct vs G3P GWSA r = 0.74.
- **TerraClimate soil-moisture route (optional, done)**: anonymous read of
  https://cpdataeuwest.blob.core.windows.net/cpdata/terraclimate.zarr fails with HTTP 409 "Public access is not permitted on this
  storage account"; it works through the Planetary Computer STAC collection `terraclimate` (signed SAS token, needs `pip install
  adlfs`). Variable `soil` (mm, end-of-month, 1/24 deg, ends 2021-12). Method: region mean (cells inside counties), anomaly vs
  2004-2009 mean, /10 -> cm; `tws_minus_tcsm_cm` = (GFZ TWS minus its 2004-2009 mean) - SM anomaly. TerraClimate's one-layer
  bucket soil moisture varies little here (r with TWS 0.07), so this GWS estimate is almost the TWS itself; prefer G3P GWSA.
- **JPL mascons** code path: `jpl_mascons_earthaccess()` in `nasa_grace_gfz.py`, run only with `WATER_CLOCK_EARTHDATA=1`
  (needs a free Earthdata login + `~/.netrc` and `pip install earthaccess`; short name TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4).
  NOT run (podaac / urs.earthdata blocked, no login). CSR mascons not attempted (TLS failure already recorded in BLOCKERS.md).

### 1c. Maps -> `grace_maps.json` (40 KB)
- `region`: GRACE-DA gws percentile at 0.125 deg over the region bbox (26 x 21 cells) for 2003, 2004, 2012, 2024 (annual means
  of the monthly samples) and the latest weekly field (2026-11-02). Top-level `cell_deg/bbox/dates/gws_pct` mirror `region`
  (contract shape). `context_high_plains`: same at 0.25 deg over [-104.5, 34, -97.5, 42].
- `tws_trend_cm_yr`: GFZ TWS per-cell trend (1 deg, 2003-latest and 2003-2016); `g3p_gws_trend_cm_yr`: G3P groundwater trend
  (0.5 deg, 2003-2023-09). `region_trends_cm_yr`: all region trends above; `region_annual_gws_pct`: annual region means.
- Grid rows run north -> south, columns west -> east, null = no data.

## 2. NASA POWER daily + FAO-56 ET0 -> `power_county_annual.parquet`
- API (one call per county centroid, community AG, 1984-01-01..2025-12-31):
  `https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M_MAX,T2M_MIN,RH2M,T2MDEW,WS2M,ALLSKY_SFC_SW_DWN,PRECTOTCORR,PS&community=AG&longitude=..&latitude=..&start=19840101&end=20251231&format=JSON`.
  26 counties x 15,341 days, no fill values. POWER is MERRA-2 (0.5 x 0.625 deg) + CERES/SRB solar (1 deg), so several
  neighbouring counties share the same underlying cell; county differences are smooth.
- ET0: FAO-56 daily Penman-Monteith (Allen et al. 1998, eq. 6) with ea from dew point (eq. 14), P from POWER PS, Rso from
  POWER cell elevation (eq. 37), albedo 0.23, G = 0, u2 = WS2M; documented in the script header.
- Columns: county_fips, year (1984-2025), precip_in, precip_gs_in (Apr-Sep), et0_in, et0_gs_in, tmax_jja_f (mean daily max
  Jun-Aug, F), tmean_f, n_days, source. 1,092 rows (26 x 42).
- Region-mean ranges: annual precip 12.8 in (2012) .. 25.8 in (2015); Apr-Sep ET0 40.9 (1992) .. 53.1 in (2012); annual ET0
  56-74 in. 1995-2014 mean precip_gs 15.3 in, et0_gs 46.2 in, tmax_jja 91.5 F.
- Extra: `power_region_daily.parquet` (date, precip_mm, et0_mm, tmax_c, tmin_c; region mean of the 26 points, 1984-2025) for
  dry-spell selection (e.g. HLS irrigation detection).

## 3. GPM IMERG -> `imerg_county_annual.parquet`
- The Planetary Computer `gpm-imerg-hhr` Zarr (IMERG V06B half-hourly) ends 2021-05-31 and is chunked as 12 half-hours x full
  globe (~55 MB/chunk): one year at one point = 1,460 chunks (~80 GB) -> annual totals from it are infeasible here.
- Used instead: **IMERG daily served by NASA POWER**, parameter `IMERG_PRECTOT`, native 0.1 deg, UTC days only
  (`time-standard=UTC`; with LST POWER returns all -999 and "The IMERG Source Data is not available at the Local Solar Time (LST)
  standard"). Header source: ['IMERG']. One point per county centroid (0.1 deg cell containing it - a point sample, not a
  county-area mean). 2001-2025 complete: 26 counties x 25 years = 650 county-years.
- Columns: county_fips, year, imerg_precip_in, imerg_precip_gs_in (Apr-Sep), n_days, power_precip_in, power_precip_gs_in, source.
- IMERG vs POWER PRECTOTCORR (2001-2025): region-mean annual r = 0.89, Apr-Sep r = 0.93; county-year r = 0.87 (per-county
  median 0.87, min 0.73). IMERG is wetter by +1.15 in/yr (+5.8%) on average (county bias -0.4 to +2.7 in); the largest gaps are
  recent years (2020 +4.0 in, 2024 +7.2 in, 2023 +3.8 in), so treat 2020+ precipitation as uncertain by several inches.
- Cross-check against the PC Zarr (V06B half-hourly summed over UTC days, 4 wettest region days of 2019-2020, 104 county-day
  pairs, 16 Zarr chunks read): r = 0.79, mean 24.6 mm (PC V06) vs 28.8 mm (POWER IMERG). Not identical (version / product
  differences), but the same storms. Pairs in `data/raw/imerg/pc_check.csv`, summary `data/raw/imerg/imerg_summary.json`.

## 4. NEX-GDDP-CMIP6 -> `cmip6_2045.json`
CMIP6_SECTION

## Failures / blockers (also in BLOCKERS.md)
- GRACE-DA 2025-10: HTTP 404 for all October-2025 weekly files tried (gap in the series).
- Planetary Computer IMERG Zarr: ends 2021-05 and its chunking makes annual totals infeasible -> POWER IMERG_PRECTOT.
- TerraClimate blob anonymous access: HTTP 409 -> worked via Planetary Computer SAS token.
- JPL/CSR mascons: not available (no Earthdata login; CSR TLS failure) -> GFZ GravIS + G3P used instead.
