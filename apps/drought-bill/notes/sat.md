# sat module: MODIS vegetation stress + NEX-GDDP-CMIP6 2045 deltas

## Scripts (re-runnable; raw reads cached under data/raw/, cached files are skipped)
```
/home/user/venv-db/bin/python pipeline/sat_modis.py       # MOD13Q1 fetch (570 items, ~9 min cold) + modis_county_year
/home/user/venv-db/bin/python pipeline/sat_cropmask.py    # crop share per MODIS pixel from the cdl module's CDL 2016 lattice (~6 s)
/home/user/venv-db/bin/python pipeline/sat_modis.py --compute   # re-aggregate after the crop mask exists (~1 min)
/home/user/venv-db/bin/python pipeline/sat_cmip6.py       # NEX-GDDP-CMIP6 fetch (600 files, ~3.3 h cold) + deltas
/home/user/venv-db/bin/python pipeline/sat_cmip6.py --compute   # deltas from the cache only (~10 s)
```
Logs: `data/raw/modis/run.log`, `data/raw/nex_gddp/run.log`. County polygons: Census `cb_2023_us_county_500k`
(`data/raw/census/`), 667 counties in IA, NE, KS, MO, IL, SD, MN. Interior points come from
`data/processed/counties.parquet` (geo module). Blockers: `notes/blockers_sat.md`.

---------------------------------------------------------------------------------------------------------------------
## 1. `data/processed/modis_county_year.parquet`

Key (fips, year), 2001-2025, **16,675 rows** (667 counties x 25 years). 2025 is all null (see the 2025 bullet below).

| column | unit | meaning |
|---|---|---|
| fips | str(5) | county |
| year | int | calendar year |
| ndvi_jul_aug | NDVI (-1..1) | pooled mean NDVI of the valid pixels from that year's July-August composites, cropland-masked where `mask` says so |
| vci_jul_aug | 0-100 | Vegetation Condition Index: 100 x (ndvi - min) / (max - min). min and max are the county's own 2001-2024 values. Values are clipped to 0-100 (only matters outside the baseline years) |
| ndvi_z | sd | (ndvi - mean) / sd, with mean and sd (ddof=1) of the county's 2001-2024 values |
| n_px | pixels | mean number of valid ~927 m pixels per composite used for ndvi_jul_aug |
| n_composites | count | composites found that year (4 normally, 3 in 2024, 0 in 2025) |
| mask | str | `cropland_cdl2016` (618 counties) or `all_land` (49 counties with fewer than 30 crop pixels: mostly northern-MN forest, Ozark MO, Cook County IL) |
| ndvi_all_land_jul_aug | NDVI | the same mean with no crop mask (every county), for comparison |
| n_px_all_land | pixels | valid pixels per composite with no crop mask |
| county_px_total, county_crop_px | pixels | MODIS overview pixels in the county, and how many of them are cropland (CDL crop share >= 0.5) |

**Source.** NASA MODIS Terra MOD13Q1 v6.1 16-day vegetation indices, read from Microsoft Planetary Computer
`modis-13Q1-061` (STAC https://planetarycomputer.microsoft.com/api/stac/v1; COGs on modiseuwest.blob.core.windows.net,
signed with `planetary_computer`). DOI 10.5067/MODIS/MOD13Q1.061.
- **Tiles.** h09v05, h10v04, h10v05, h11v04, h11v05, h12v04. These are computed by intersecting the county polygons
  with the sinusoidal tile grid. h09v05 is needed for western KS and h12v04 for Cook County MN. h09v04 is not needed.
- **Composites.** Terra only, compositing start date in July or August: DOY 193, 209, 225, 241 (Jul 11/12 to Sep 13/14).
  That is 4 per tile-year, 570 items in total after de-duplication. PC holds two production versions of 2005 DOY 241 and
  2021 DOY 225; the newer one is used. Aqua (MYD13Q1) was not used. It starts in mid-2002, which would make the record
  inconsistent. It also has the same 2025 gap, so it would not help.
- **Resolution.** The NDVI and `pixel_reliability` COGs are read at overview level 1 (factor 4): 1200 x 1200 pixels of
  926.6 m per tile, about 2.2 MB per item in total.
  - The overviews are block averages. For one tile (h10v04, 2012 DOY 209), the overview NDVI minus the mean of the
    good full-resolution 4x4 block averaged -0.00015 NDVI, with a 1-99% range of +-0.033.
  - That averaging also means the reliability overview is an average.
- **Quality mask.** A pixel is kept when `pixel_reliability` <= 1 (good or marginal) and NDVI is between -0.2 and 1.0.
  A single fill (255) or cloud/snow (2/3) sub-pixel pushes the averaged reliability above 1, so those pixels drop out.
  About 98% of pixels pass in a clear composite.
- **Cropland mask.**
  - Each ~927 m MODIS pixel gets the share of CDL **2016** points (the cdl module's 240 m lattice,
    `data/raw/cdl/lattice_2016.npy`, read only) whose CDL code is a cultivated crop. Crop codes are 1-60, 66-80 and
    200-255. Fallow (61), pasture and grass (62, 171, 176, 181), forest, water, developed and wetland count as not crop.
  - Pixels with a crop share of at least 0.5 count as cropland.
  - The same static mask is used for every year.
  - Counties with fewer than 30 cropland pixels use all land instead (`mask` column).
  - Across all county-years, crop-masked NDVI correlates 0.957 with all-land NDVI.
- **County aggregation.** Each county polygon is rasterised onto each tile's 927 m sinusoidal grid by pixel centre.
  The mean pools all valid pixel-composites in the county for the year, across tiles. VCI is computed from the county
  mean NDVI, not as a mean of pixel-level VCI.

**Coverage.**
- 2001-2024: all 667 counties every year, with no missing values.
- 2025: null. PC has no Jul-Nov 2025 MODIS composites (blockers_sat.md #1).
- 2024: built from 3 composites, because DOY 225 is missing on PC. In 2001-2023, a 3-composite mean is lower than the
  4-composite mean by 0.004 NDVI on average (sd 0.008, r = 0.998). So 2024 VCI is probably biased low by a few points.
- n_px (crop-masked) has a median of about 1,100 pixels per composite, with a minimum of 29.

**Sanity checks (median VCI by state).**
| year | IA | IL | KS | MN | MO | NE | SD |
|---|---|---|---|---|---|---|---|
| 2002 | 64 | 54 | 24 | 71 | 55 | 4 | 26 |
| 2012 | 0 | 0 | 0 | 44 | 0 | 6 | 12 |
| 2021 | 81 | 86 | 79 | 53 | 86 | 83 | 60 |
| 2022 | 90 | 100 | 44 | 86 | 85 | 60 | 64 |
| 2023 | 77 | 89 | 77 | 51 | 88 | 80 | 81 |

- **2012.** Region mean VCI is 11.4. 77% of counties are below 20 and 67% are at or below 10. Only northern MN stays
  near normal.
- **2022.** KS, NE and SD are clearly the low states: mean VCI 49, 56 and 61, with mean ndvi_z -0.51, -0.38 and +0.06.
  IA, IL and MN read as greener than normal.
- **Other known droughts.** NE 2002, SD 2006, MN 2021 and MN 2023 also show up.
- **Plymouth County IA (19149).** NDVI 0.695 in 2012 (z = -4.1, VCI 0). 2022 is near normal (VCI 76). July-August
  NDVI over dense corn saturates, so moderate drought in NW Iowa in 2022 hardly shows.

**Caveats.**
- Because 2012 is extreme, it sets each county's minimum. Every other year therefore gets a fairly high VCI.
  `ndvi_z` is less dominated by 2012.
- July-August NDVI is a canopy greenness signal. It saturates over healthy corn and soybeans, so it understates
  moderate drought and yield loss in the Corn Belt.
- The crop mask is static (CDL 2016). It is not crop-specific, and at the ~1 km scale mixed pixels with 50-100% crop
  are included.
- Terra's orbit has drifted since about 2020, moving the overpass time earlier. MOD13Q1 v6.1 is not adjusted for this.
  The effect on 16-day maximum-value NDVI composites is expected to be small, but it is not quantified here.

---------------------------------------------------------------------------------------------------------------------
## 2. `data/processed/cmip6_deltas.parquet` and `data/processed/cmip6_period_means.parquet`

**Source.** NASA NEX-GDDP-CMIP6 (daily, 0.25 deg, bias-corrected and spatially disaggregated CMIP6), read from Microsoft
Planetary Computer `nasa-nex-gddp-cmip6` (STAC; NetCDF4 files on nasagddp.blob.core.windows.net, signed with
`planetary_computer`). Member r1i1p1f1 for every model. Variables: pr, tasmax, tasmin, hurs.
- **Models (5).** ACCESS-CM2, GFDL-ESM4, MPI-ESM1-2-HR, MRI-ESM2-0, NorESM2-MM.
- **Scenarios.** historical, ssp245, ssp585.
- **Years (subsampled, every other year: 10 per period).**
  - historical 1995-2014: 1995, 1997, ..., 2013.
  - ssp245 and ssp585 2035-2054: 2035, 2037, ..., 2053.
  - In total 600 variable-years, all read with no failures.
- **Why subsample.**
  - ds.nccs.nasa.gov is blocked, so there is no server-side subsetting (blockers_sat.md #3).
  - Each file is chunked as one full global day per chunk. Reading only Jun-Aug still costs 92 chunks, or 45-71 MB per
    variable-year.
  - At about 3 MB/s through the proxy, the 600 reads took about 3.3 h. Full 20-year periods would have taken about
    6.5 h.
- **Read path.** Adapted from `context_climate.py` `read_pc`:
  1. h5py over fsspec reads the HDF5 chunk index.
  2. HTTP range requests fetch only the Jun-Aug chunks (8 threads, 2 files in flight).
  3. Each chunk is decompressed locally (zlib plus unshuffle) and cut to the box lon -105..-87, lat 35..50
     (60 x 72 cells).
  4. The cache is `data/raw/nex_gddp/<model>/<scenario>/<var>_<year>.npz` (637 MB). Each file records its source URL
     and calendar.
  - Jun-Aug is selected by calendar month (92 days in every calendar these models use).
- **Per cell and year.**
  - pr kg m-2 s-1 x 86400 gives mm/day. Temperatures are converted K to degC. tasmin is capped at tasmax.
  - edd30 = single-sine degree-days above 30 C from daily tasmin/tasmax. The function is identical to
    `hazard_power.py::sine_dd_above`.
  - VPD follows the hazard module's RH form: es = mean(es(Tmax), es(Tmin)) and ea = es((Tmax+Tmin)/2) x hurs/100,
    clipped at 0, in kPa. The hazard module derives ea from POWER QV2M (RH2M fallback). The NEX form is the closest
    equivalent with hurs.
- **County value.**
  - Mean of the 0.25 deg cells whose centres fall inside the county polygon. That is 660 counties, with a median of
    3 cells (range 1-31).
  - 7 small counties contain no cell centre and use the cell nearest the interior point (`cell_method = nearest_cell`):
    17069, 17155, 20043, 27123, 29171, 29227 and 29510.
  - Indices are averaged over the years first, then over the cells.

### `cmip6_deltas.parquet`: key (fips, gcm, scenario), 6,670 rows (667 counties x 5 GCMs x 2 scenarios), no nulls
| column | unit | meaning (2035-2054 minus 1995-2014, each period a 10-year mean) |
|---|---|---|
| d_prcp_jja_pct | % | 100 x (future JJA total / historical JJA total - 1) |
| d_edd30_jja | degC-days | change in JJA extreme degree days above 30 C (single sine) |
| d_tmax_jja_c | degC | change in mean JJA daily max temperature |
| d_vpd_jja | kPa | change in mean JJA VPD (from hurs, tasmax, tasmin) |
| d_tmin_jja_c | degC | change in mean JJA daily min temperature |
| d_prcp_{jun,jul,aug}_pct, d_tmax_{jun,jul,aug}_c, d_tmin_{jun,jul,aug}_c | %, degC | monthly changes, for a monthly delta-method shift of daily POWER data |
| hist_period, fut_period, n_years_hist, n_years_fut | | "1995-2014", "2035-2054", 10, 10 |

### `cmip6_period_means.parquet`: key (fips, gcm, scenario), 10,005 rows (667 x 5 x 3, historical included)
Raw period means per county and GCM, for applying a delta-method shift to the NASA POWER 1981-2025 climatology.
Columns: period, n_years, years_used, n_cells, cell_method, prcp_jja_mm, tmax_jja_c, tmin_jja_c, edd30_jja,
prcp_{jun,jul,aug}_mm, tmax_{jun,jul,aug}_c, tmin_{jun,jul,aug}_c, vpd_jja_kpa, hurs_jja_pct.
Units are mm per season or month, degC, degC-days, kPa and %.
Suggested use:
- Add the monthly tmax and tmin shifts to POWER daily T2M_MAX and T2M_MIN.
- Multiply daily precipitation by the monthly precipitation ratio.
- Recompute edd30 from the shifted daily values. This captures the nonlinearity better than adding d_edd30_jja.

**Results (mean over the 667 counties).**
| scenario | gcm | d_prcp_jja_pct | d_edd30_jja | d_tmax_jja_c | d_vpd_jja |
|---|---|---|---|---|---|
| ssp245 | ACCESS-CM2 | -2.2 | 74.8 | 3.29 | 0.40 |
| ssp245 | GFDL-ESM4 | 10.7 | 29.7 | 1.66 | 0.16 |
| ssp245 | MPI-ESM1-2-HR | 4.3 | 11.4 | 0.79 | 0.06 |
| ssp245 | MRI-ESM2-0 | 7.2 | 30.2 | 1.68 | 0.10 |
| ssp245 | NorESM2-MM | -4.9 | 45.8 | 2.34 | 0.31 |
| ssp585 | ACCESS-CM2 | 7.5 | 47.3 | 2.34 | 0.16 |
| ssp585 | GFDL-ESM4 | 2.6 | 29.7 | 1.80 | 0.18 |
| ssp585 | MPI-ESM1-2-HR | -4.1 | 29.1 | 1.62 | 0.20 |
| ssp585 | MRI-ESM2-0 | 2.4 | 51.1 | 2.27 | 0.20 |
| ssp585 | NorESM2-MM | -3.5 | 66.2 | 3.11 | 0.39 |
| **ssp245** | **5-GCM mean** | **+3.0** | **+38.4** | **+1.95** | **+0.21** |
| **ssp585** | **5-GCM mean** | **+1.0** | **+44.7** | **+2.23** | **+0.23** |

**Sanity checks.**
- **EDD30.** The ensemble-mean d_edd30_jja is positive in every county under both scenarios: ssp585 minimum +3.7 and
  mean +44.7 degC-days; ssp245 mean +38.4. 99.9% of individual county x GCM x scenario rows are positive.
- **By state, ssp585 ensemble d_edd30.** KS +74, NE +51, MO +48, IL +38, SD +38, IA +34, MN +24 degC-days. The south
  and west warm the most in heat-stress terms.
- **Precipitation.** The JJA change has no consistent sign across models (from -5% to +11% by model). The models
  agree more on July (+9% ensemble) than on August (-2% to +1%).
- **Historical NEX vs NASA POWER over 1995-2014, county means.**
  - JJA precipitation: 273 vs 291 mm (r = 0.94).
  - Tmax: 30.4 vs 29.6 C (r = 0.95).
  - EDD30: 47 vs 43 degC-days (r = 0.91).
  - VPD: 1.11 vs 1.27 kPa (r = 0.95).
  - The levels differ, which is why the deltas (or the delta method), and not raw NEX values, should be combined with
    POWER.

**Caveats.**
- With 10 sampled years per 20-year period, internal variability is large, especially for precipitation and for
  ssp245 vs ssp585 at mid-century. By 2045 the two scenarios differ little: the ensemble d_tmax is +1.95 vs
  +2.23 C. ACCESS-CM2 even shows ssp245 warmer than ssp585 (+3.29 vs +2.34 C), which is sampling noise. Use the
  ensemble mean, and treat the model spread as the uncertainty range.
- The 5 models and their single members understate the CMIP6 spread. ACCESS-CM2 and NorESM2-MM are the warm
  outliers, and MPI-ESM1-2-HR is the cool one.
- The 0.25 deg cells (~25 km) are coarse relative to counties. Neighbouring small counties can share cells.
- The VPD definition differs slightly from the hazard module (hurs-based ea instead of QV2M-based ea). Apply d_vpd as a
  difference only.
- PC file versions are whatever PC hosts. The URL of every source file is stored in its cache .npz (`src`).
