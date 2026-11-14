# hazard module: NASA POWER drought hazard + US Drought Monitor

## Scripts (re-runnable; raw downloads are cached and skipped on re-run)
```
/home/user/venv-db/bin/python pipeline/hazard_power.py    # POWER fetch (424 cells) + hazard_county_year; ~4 min cold, ~35 s cached
/home/user/venv-db/bin/python pipeline/hazard_usdm.py     # USDM fetch (7 states x 26 years x 2 endpoints) + usdm_county_year; ~45 s cold, ~9 s cached
/home/user/venv-db/bin/python pipeline/hazard_checks.py   # sanity checks below (prints a report)
```
Logs of the last run: `data/raw/power/run.log`, `data/raw/power/checks.log`.

## Precipitation source: NASA POWER, not GPM IMERG
GPM IMERG was the intended precipitation source, but the IMERG Zarr storage host is not reachable from this environment,
so all precipitation here is NASA POWER `PRECTOTCORR`. POWER's own parameter metadata
(`https://power.larc.nasa.gov/api/system/manager/parameters/PRECTOTCORR?community=AG&temporal=daily`) defines it as
"The average MERRA-2 bias corrected total precipitation at the surface of the earth" (mm/day), and the daily API
response header lists sources `["MERRA2", "POWER"]`. So it is MERRA-2 bias-corrected precipitation on the MERRA-2 grid,
not a gauge or satellite product at county scale.

## Inputs
- County interior points: `data/processed/counties.parquet` (geo module; 667 counties: IA 99, IL 102, KS 105, MN 87,
  MO 115, NE 93, SD 66). The script falls back to Census `cb_2023_us_county_500k` representative points if that file is
  missing. The fallback was not needed for this run.
- NASA POWER Daily API v2.10.3, `https://power.larc.nasa.gov/api/temporal/daily/point`, community AG, 1981-01-01 to
  2025-12-31, times in LST, parameters T2M, T2M_MAX, T2M_MIN, PRECTOTCORR, GWETROOT, GWETTOP, QV2M, RH2M.
  ALLSKY_SFC_SW_DWN was not fetched (optional in the contract).
- USDM Data Services: `https://usdmdataservices.unl.edu/api/CountyStatistics/GetDroughtSeverityStatisticsByAreaPercent`
  and `.../CountyStatistics/GetDSCI`, `aoi=<state abbr>`, one calendar year per request, `statisticsType=1`.

## POWER grid and dedupe
POWER meteorology comes from MERRA-2 on its native 0.5 deg lat x 0.625 deg lon grid. Cell centres sit at lat multiples
of 0.5 and lon multiples of 0.625. Each county goes to the cell containing its interior point
(`round(lat/0.5)*0.5`, `round(lon/0.625)*0.625`), and the API is queried once per cell at the cell centre.
That gives **424 unique cells for 667 counties** (1-4 counties per cell, mean 1.57). I checked this for three counties
(19149 Plymouth IA, 17031 Cook IL, 27137 St. Louis MN): a request at the county point and a request at its cell
centre return identical values. All counties in a cell share the same weather; this is a regional signal, not a
field-scale one. Fetching used 5 concurrent requests with exponential backoff. All 424 cells succeeded on the first
pass, in 211 s. GWETROOT and GWETTOP are 0-1 wetness fractions from the MERRA-2 land model.

## Output files

### data/processed/hazard_county_year.parquet: 30,015 rows = 667 counties x 45 years (1981-2025), key (fips, year)
2025 is complete: POWER served data through 2025-12-31, so `is_partial_year` is False everywhere. No nulls in any metric.
POWER returned no fill values (-999) for any variable, cell or day.
Climatology base for every anomaly, percentile, SPI and z-score: **1991-2020, per POWER cell** (= per county).

| column | unit | definition |
|---|---|---|
| fips, year, state_abbr, name | | key and labels (from counties.parquet) |
| power_cell_id, power_cell_lon, power_cell_lat | deg | POWER/MERRA-2 cell (`p<lat:.2f>_<lon:.3f>`) and its centre |
| prcp_jja_mm | mm | sum of daily PRECTOTCORR, Jun 1-Aug 31 |
| prcp_jul_mm | mm | Jul 1-31 sum (corn silking window) |
| prcp_aug_mm | mm | Aug 1-31 sum (soybean pod fill) |
| prcp_mjjas_mm | mm | May 1-Sep 30 sum |
| prcp_jja_anom_pct | % | 100 x (prcp_jja / 1991-2020 mean - 1) |
| spi_jja | - | SPI of JJA total: 2-parameter gamma (loc=0, MLE, scipy) fitted to the cell's 1991-2020 JJA totals, then the gamma CDF mapped to a standard normal (CDF clipped to [1e-6, 1-1e-6]; no zero totals occur) |
| prcp_mj_mm, prcp_mj_anom_pct | mm, % | extra: May 1-Jun 30 sum and its anomaly vs 1991-2020 (added because the 2023 IL/MO drought was mostly May-June; see checks) |
| edd30_jja | degC-day | extreme degree days above 30 C, Jun-Aug sum. Each day uses single-sine interpolation between T2M_MIN and T2M_MAX (Baskerville & Emin 1969) |
| gdd10_30_mjjas | degC-day | May-Sep sum of sine degree days above 10 C minus those above 30 C (the Schlenker-Roberts 10-30 C band, same sine method) |
| tmax_jja_c | degC | mean daily T2M_MAX, Jun-Aug |
| vpd_jja_kpa | kPa | mean daily VPD, Jun-Aug, FAO-56: es = [es(Tmax)+es(Tmin)]/2 (Tetens), ea from QV2M: ea = q P / (0.622 + 0.378 q), with P from cell elevation (FAO-56 eq. 7; elevation from the POWER response). The code falls back to ea = es(T2M) x RH2M/100 if QV2M is missing (it never was). Clipped at 0 |
| gwetroot_jja | 0-1 | mean GWETROOT (root-zone soil wetness), Jun-Aug |
| gwetroot_jul_aug | 0-1 | mean GWETROOT, Jul-Aug |
| gwetroot_jja_pct | 0-100 | empirical percentile of gwetroot_jja within the cell's 1991-2020 values: 100 x (#base < x + 0.5 x #base == x) / 30 |
| gwettop_jja | 0-1 | extra: mean GWETTOP (surface wetness), Jun-Aug |
| z_neg_spi_jja, z_edd30_jja, z_neg_gwetroot_jja | sd | z-scores of -spi_jja, edd30_jja and -gwetroot_jja vs the cell's 1991-2020 mean and SD (ddof=1) |
| hazard_n_components | count | number of non-null z components (3 for every row) |
| **hazard_z** | sd | **composite drought hazard = mean of z_neg_spi_jja, z_edd30_jja, z_neg_gwetroot_jja**. Higher = drier and hotter. A component whose 1991-2020 SD is 0 would be null and the mean would skip it; this never happened |
| n_days | days | days of POWER data in the year (365/366) |
| is_partial_year | bool | True only if the year's data ends before Dec 31 (none) |

### data/processed/power_cells.parquet: 424 rows, key cell_id
cell_id, lon, lat (cell centre), elev_m (MERRA-2 cell elevation from the POWER response), n_counties,
fips (list of county fips whose interior point falls in the cell), fetch_status ("ok" for all).

### data/processed/power_daily_cells.parquet: 6,968,864 rows (424 cells x 16,436 days), 86 MB (zstd)
cell_id, date, T2M, T2M_MAX, T2M_MIN (degC), PRECTOTCORR (mm/day), GWETROOT, GWETTOP (0-1), QV2M (g/kg), RH2M (%),
stored as float32, 1981-01-01 to 2025-12-31, 0% missing. Raw JSON per cell: `data/raw/power/<cell_id>_1981_2025.json.gz`.

### data/processed/usdm_county_year.parquet: 17,342 rows = 667 counties x 26 years (2000-2025), key (fips, year)
Built from 905,119 weekly county rows (`data/raw/usdm/usdm_county_weekly.parquet`). Raw JSON is cached as
`data/raw/usdm/{area,dsci}_<ST>_<year>.json.gz`. Every county in counties.parquet has USDM data, and USDM returned no
county outside that list. No request failed. A week belongs to a month by its `mapDate` (the USDM valid date, a
Tuesday), so JJA has 13-14 weeks. Percentages are cumulative (statisticsType=1): d2 = % of county area in D2-D4.
On every row d0 >= d1 >= d2 >= d3 >= d4 holds. GetDSCI matches d0+d1+d2+d3+d4 to within 0.54 on every week (rounding).

| column | unit | definition |
|---|---|---|
| dsci_jja_mean | 0-500 | mean of weekly DSCI (from GetDSCI; sum of cumulative D0-D4 percents if a week were missing from GetDSCI) over weeks with mapDate in Jun-Aug |
| dsci_jja_max | 0-500 | extra: max weekly DSCI, Jun-Aug |
| d1plus_pct_jja_mean, d2plus_pct_jja_mean | % area | extra: mean weekly % area in D1+ / D2+, Jun-Aug |
| d2plus_pct_jja_max | % area | max weekly % area in D2-D4, Jun-Aug |
| d3plus_pct_jja_max | % area | max weekly % area in D3-D4, Jun-Aug |
| weeks_d2plus_jja | weeks | JJA weeks with any D2+ area (> 0%) |
| weeks_d2plus50_jja | weeks | extra: JJA weeks with D2+ covering >= 50% of the county |
| n_weeks_jja | weeks | USDM weeks in Jun-Aug (13 or 14) |
| dsci_mjjas_mean, dsci_annual_mean | 0-500 | extra: mean weekly DSCI over May-Sep and over the calendar year |

## Sanity checks (pipeline/hazard_checks.py)
**1. 2012 is the most extreme year in most of the region: PASS, with 1988 as a close rival.**
- Region-mean hazard_z: 2012 = 2.11 is the highest of 1981-2025 (1988 = 1.90, 2006 = 1.00).
- 2012 region means: edd30_jja 117 degC-day, spi_jja -1.89, JJA precip -47%, gwetroot percentile 5.
- 2012 is the top state-mean hazard_z year in IL, KS, MO, NE and SD. In IA, 1988 and 2012 tie at 2.33. In MN, 1988
  (2.91) is first and 2012 is not in the top 3; the 2012 drought was weaker in northern MN (spi -1.31).
- By county, 2012 is the maximum-hazard_z year for 55% of counties (MO 90%, NE 89%, IL 63%; MN 6%), and 1988 for 33%.
- 2012 has the highest edd30_jja for 54% of counties and the lowest spi_jja for 34%.
- Every county in IA, IL and MO has spi_jja < -1 in 2012.
- 2012 edd30_jja is about 5x the 1991-2020 normal in IA (97.6 vs 17.9) and IL (114 vs 19).

**2. 2022 dry in NE/KS/SD: PASS.**
- State-mean spi_jja in 2022: NE -1.40 (89% of counties < -1), KS -0.91, SD -0.89.
- 2022 hazard_z: NE 1.43, KS 0.96, SD 0.75, vs IL 0.10.
- KS edd30_jja was 131 vs a 79 normal.
- Western IA was dry too (state spi -0.68; Plymouth 19149 spi -1.35, hazard_z 1.59).
- USDM agrees: 2022 dsci_jja_mean NE 219, KS 186, SD 98, vs IL 41.

**3. 2023 dry in IA/IL/MN/MO: PASS for IA and MN; PARTIAL for IL and MO.**
- IA: spi_jja -1.16, hazard_z 1.11. MN: spi_jja -1.70, hazard_z 1.18.
- IL and MO: JJA precipitation was near normal (spi -0.24 / -0.19), but root-zone wetness was low (gwetroot_jja_pct
  11 / 16) and hazard_z was elevated (0.69 / 0.72).
- The IL/MO deficit fell in May-June: May-Jun 2023 precipitation was -51% in IL and -52% in MO (IA -45%, MN -38%).
  July-August then recovered there (Aug: IL +23%, MO +48%). That is why `prcp_mj_mm` / `prcp_mj_anom_pct` were added.
- USDM 2023 dsci_jja_mean: IA 212, MO 211, MN 177, IL 159. USDM integrates the spring deficit, so it sees 2023 as
  more severe in IL/MO than a JJA-only precipitation index does.

**4. hazard_z vs USDM dsci_jja_mean, county-years 2000-2024 (n = 16,675):**
- Pearson **+0.649**, Spearman **+0.716**.
- Within-county (county-demeaned) Pearson +0.668.
- Region-year means (n = 25) Pearson +0.864.
- By state: IA 0.72, IL 0.79, KS 0.55, MN 0.66, MO 0.74, NE 0.66, SD 0.64.
- Components vs DSCI: spi_jja -0.49, edd30_jja +0.61, gwetroot_jja_pct -0.61 (Spearman -0.70).
- hazard_z vs d2plus_pct_jja_max: +0.56.

## Caveats
- **Resolution:** MERRA-2 cells are about 55 x 50 km. All counties in a cell share identical weather, and a county is
  represented by the single cell containing its interior point, not an area average.
  - Large or elongated counties, and counties near cell edges, may be poorly represented.
  - Cook County IL's point is about 0.004 deg from a cell edge.
- **PRECTOTCORR** is reanalysis precipitation (MERRA-2, bias corrected). It is not IMERG or gauge data. Convective
  summer rain is smoothed, so single-county JJA totals can differ substantially from station records.
- **GWETROOT** is a MERRA-2 land-model state, not an observation. Its absolute level varies by cell, which is why the
  hazard uses within-cell z-scores and percentiles.
- **hazard_z** is unweighted and JJA-only. It misses spring-only droughts (e.g. IL/MO 2023, see check 3) and
  late-season (September) drought. edd30_jja is right-skewed (z up to 8), so heat dominates hazard_z in extreme years.
- **VPD** uses daily mean QV2M with Tmax/Tmin saturation (FAO-56). The CMIP6 deltas (sat module) will likely use
  hurs/tas, so compare deltas, not levels.
- **USDM** is an expert-blended drought depiction with memory (multi-week to multi-month). It is not a pure JJA weather
  index, so a correlation of about 0.65-0.7 with a JJA weather composite is expected. USDM starts in 2000.
- **Unused fallback:** the census fallback path in hazard_power.py was not exercised in this run.
