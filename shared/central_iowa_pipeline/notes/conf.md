# Module `conf`: terrain, soils and weather confounders

Owner files: `pipeline/conf_*.py`, `data/confounders.parquet`, `data/weather_annual.parquet`,
`data/weather_daily_power.parquet`, `notes/conf.md`. Intermediate and raw caches are in `data/raw/{nasadem,gnatsgo,sda,power,imerg,conf}/`.

## How to re-run
```
.venv/bin/python pipeline/conf_run_all.py
```
This runs `conf_weather.py`, then `conf_terrain.py`, `conf_soils.py`, `conf_imerg.py` and finally `conf_assemble.py`. Every step caches its raw downloads, so a re-run only recomputes.
- `conf_imerg.py` takes two environment variables: `TOP_K` (wettest days sampled per year, default 6) and `YEARS` (default `2016-2020`). A cold run of it takes about 30-40 min because it has to download about 6.6 GB.
- Each of the other steps finishes in under 3 min on a cold run.

## data/confounders.parquet: 50,850 rows (all grid points), key `field_id`
| column | units / meaning | source |
|---|---|---|
| field_id, grid_id | 'f'+5-digit grid_id, as in region.json | |
| elev_m | m, mean over a 3x3 (90 m) window | NASADEM (NASA SRTM reprocessed), 1 arcsec, bilinear to 30 m UTM 15N |
| slope_pct | percent (100·tanβ), Horn 3x3 on the DEM after Gaussian smoothing (σ = 1 px), 3x3 mean | NASADEM |
| curvature | profile curvature (Zevenbergen-Thorne), **convex > 0**, units 1/(100 m), from the DEM smoothed with σ = 1.5 px, 3x3 mean | NASADEM |
| twi | ln(a / tanβ). a = flowacc·30 m (specific catchment area, m), tanβ floored at 0.001. 3x3 mean | NASADEM |
| flowacc | upslope contributing area in **30 m cells, counting the cell itself** (multiply by 900 for m²). D8 on a priority-flood-conditioned DEM (Barnes et al. 2014); 3x3 **median** | NASADEM |
| mukey | SSURGO/gNATSGO map unit key at the point (pixel containing the point, 20 m overview, nearest) | gnatsgo-rasters (PC) |
| aws0_100 | mm, available water storage 0-100 cm | gnatsgo-rasters |
| soc0_30 | g C / m², soil organic carbon 0-30 cm | gnatsgo-rasters |
| nccpi3corn, nccpi3soy | 0-1, National Commodity Crop Productivity Index v3 | gnatsgo-rasters |
| droughty | 0/1, drought-vulnerable soil flag | gnatsgo-rasters |
| rootznaws | mm, root-zone available water storage | gnatsgo-rasters |
| kwfact | K factor (whole soil, rock fragments included) of the surface horizon | SDA chorizon |
| om_r | % organic matter, surface horizon | SDA chorizon |
| clay_pct, sand_pct | %, surface horizon (`claytotal_r`, `sandtotal_r`) | SDA chorizon |
| drainagecl, hydgrp | drainage class and hydrologic group of the dominant component | SDA component |
| power_cell_id | NASA POWER (MERRA-2) cell containing the point, `p<lat:.2f>_<lon:.3f>` | |
| flowacc_center | flowacc at the centre pixel, with no window. It is very heavy-tailed because it picks up channels | NASADEM |
| ssurgo_muname, ssurgo_compname, ssurgo_comppct_r, ssurgo_slope_r | map unit name, dominant component and its percent, representative slope (%) | SDA |
| surf_hzname, surf_hz_bottom_cm | name and bottom depth (cm) of the surface horizon used | SDA |

"Dominant component" means the component with the highest `comppct_r` (ties broken by cokey). "Surface horizon" means the component's horizon with the smallest `hzdept_r`; it starts at 0 cm in every case.

### Sanity stats (confounders)
- elev_m runs from 183 to 407 m across the tile buffer, with a point mean of 305 m.
- slope_pct: median 3.0, mean 3.8, 99th percentile about 15, max 39.
- Agreement with SSURGO: the Spearman correlation between slope_pct and SSURGO `slope_r` is 0.43. That is expected, since `slope_r` is a single value for a whole map unit.
- TWI and slope follow drainage class in the expected direction:

  | drainage class | median TWI | median slope_pct |
  |---|---|---|
  | very poorly drained | 9.16 | 2.1 |
  | poorly drained | 8.63 | 2.4 |
  | somewhat poorly drained | 8.26 | 2.7 |
  | moderately well drained | 7.89 | 3.8 |
  | well drained | 7.72 | 3.8 |
- Curvature: the median is +0.0022 on map units named "...eroded" and -0.0015 elsewhere. Eroded shoulders are convex, as expected.
- Soils: 1,179 unique mukeys, of which SDA returned 1,176. The most common component is Clarion (9,324 points). Means: kwfact 0.29, om_r 4.7%, clay 26.7%, aws0_100 181 mm, nccpi3corn 0.76.
- Missing values:
  - Terrain: 0%.
  - mukey: 0%.
  - gNATSGO properties: 1.5-2.3% missing.
  - SDA horizon properties: about 2.6% missing.

  The missing soil rows are almost all map units with no soil horizons: Water (424 points), Urban land (286), Orthents (151), Pits, sewage lagoons and similar.

## data/weather_daily_power.parquet: 144,639 rows, key (power_cell_id, date)
- Coverage: 9 cells × 16,071 days (1981-01-01 to 2024-12-31).
- Columns: power_cell_id, date, cell_lat, cell_lon, cell_elev_m, T2M, T2M_MAX, T2M_MIN (°C), PRECTOTCORR (mm/day), RH2M (%), GWETROOT and GWETTOP (0-1), ALLSKY_SFC_SW_DWN (MJ/m²/day; the POWER AG community uses MJ).
- Source: NASA POWER daily point API, community AG, v2.10.3, times in LST. Raw JSON is cached in `data/raw/power/`.
- **Cell grid:** POWER meteorology is MERRA-2 on its native **0.5° lat × 0.625° lon** grid. I verified this by probing the API: values change at latitudes x.25/x.75 and at longitudes -94.0625/-93.4375. The 9 cells covering the tile are centred at lat {41.5, 42.0, 42.5} × lon {-94.375, -93.75, -93.125}. The contract says "0.5 deg cell"; the true longitude spacing is 0.625°.
- Points per cell range from 1,079 to 12,460.
- Missing data: ALLSKY_SFC_SW_DWN is missing for all of 1981-1983 (POWER solar starts in 1984) and on 4 other days. All other fields are 0% missing.

## data/weather_annual.parquet: 396 rows, key (power_cell_id, year), years 1981-2024
| column | definition |
|---|---|
| gdd_may_sep | °C-days, 1 May-30 Sep, Σ[(min(Tmax,30) + max(Tmin,10))/2 − 10], with Tmax and Tmin each clamped to the 10-30 °C range (the 86/50 °F method) |
| hdd30_jul_aug | °C-days above 30 °C in Jul-Aug, single-sine method from Tmin/Tmax (Baskerville-Emin) |
| days_tmax30_jul_aug | count of days in Jul-Aug with T2M_MAX > 30 °C |
| prcp_amj, prcp_jja, prcp_annual | mm, sums of PRECTOTCORR |
| tmax_jul | °C, mean July T2M_MAX |
| vpd_jja | kPa, mean over Jun-Aug of es(T2M)·(1 − RH2M/100), with es from Tetens: 0.6108·exp(17.27T/(T+237.3)) |
| gwetroot_apr | mean April GWETROOT (0-1, root-zone wetness) |
| gwettop_amj | mean Apr-Jun GWETTOP (0-1) |
| srad_jja | MJ/m²/day, mean Jun-Aug solar. Null for 1981-1983 |
| frost_last_spring_doy, frost_first_fall_doy | day of year of the last day before 1 Jul and the first day from 1 Jul on with T2M_MIN ≤ 0 °C |
| n_days | days in the year (365 or 366) |
| imerg_max30min_amj | mm/h. Maximum IMERG half-hourly rate over the sampled AMJ storm days and the pixels in the cell. See the IMERG section |
| imerg_r_factor | MJ mm ha⁻¹ h⁻¹. Sum of EI30 over the sampled AMJ storm days, averaged over pixels. It is a **lower bound** on AMJ erosivity. See the IMERG section |
| imerg_n_days_sampled | number of storm days read for that year |

### Sanity stats (annual, means over cells)
| quantity | mean | range |
|---|---|---|
| gdd_may_sep | 1,594 °C-days (about 2,870 °F GDD) | 1,189-1,893 |
| prcp_annual | 869 mm | 498-1,432 |
| prcp_jja | | up to 825 mm (1993) |
| tmax_jul | 29.3 °C | 24.2-37.7 (2012) |
| vpd_jja | 0.82 kPa | |
| gwetroot_apr | 0.60 | |
| frost_last_spring_doy | 114 (about 24 Apr) | |
| frost_first_fall_doy | 286 (about 13 Oct) | |

Known extreme years show up as expected:
- **1988 and 2012 droughts:** hdd30 of 76 and 88 °C-days, vpd_jja of 1.81 and 1.69 kPa, gwetroot_apr of 0.53.
- **1993 flood:** gdd of 1,335, hdd30 of 0.1, vpd of 0.36, gwetroot_apr of 0.73.
- **2021-2023 dry, hot run:** vpd_jja of 1.11-1.18, gwetroot_apr of 0.53-0.55.

Mean annual precipitation is higher in the east of the tile (about 900 mm) than in the west (about 830 mm).

## IMERG (GPM IMERG V06 half-hourly, `precipitationCal`, from the Planetary Computer `gpm-imerg-hhr` Zarr)
Two facts limited what I could do:
1. **Coverage.** The PC collection ends on **2021-05-31**. Inside the 2016-2024 panel, only AMJ 2016-2020 is complete. Rows for 1981-2015 and 2021-2024 have null IMERG fields: 2021 has no June, and 2022-2024 are not hosted. Without Earthdata there is no other source.
2. **Throughput.** Each Zarr chunk holds 12 half-hours of the whole globe, about 55 MB compressed. I measured about 4 MB/s aggregate throughput, so one full AMJ season (364 chunks, about 20 GB) would take more than 80 min per year. That is over the 40-min time box.

**What I did instead: a time subsample.**
- For each year I picked the **6 wettest AMJ local days**, ranked by NASA POWER PRECTOTCORR (the maximum over the 9 cells).
- For each of those days I read the 4 chunks spanning 06 UTC on day d to 06 UTC on day d+1 (roughly the CST day). That is 120 chunks, which took 26 min.
- From each chunk I kept the 0.1° IMERG box over the 9 POWER cells (16 × 19 pixels), cached in `data/raw/imerg/chunk_<i>.npz`.
- The sampled days are listed in `data/raw/conf/imerg_sampled_days.json`.

**Metrics per POWER cell** (30-35 IMERG pixels each):
- `imerg_max30min_amj`: the maximum half-hourly rate over the sampled days and pixels.
- `imerg_r_factor`: the mean over pixels of Σ EI30, computed as follows:
  - a storm is one sampled local day with at least 12.7 mm at the pixel;
  - unit energy is e = 0.29[1 − 0.72·exp(−0.05·i)] MJ ha⁻¹ mm⁻¹ (RUSLE, Brown & Foster 1987);
  - I30 is the maximum half-hour intensity.

**Results** for 45 rows (9 cells × 2016-2020):
- imerg_max30min_amj: mean 24.6 mm/h, range 13-63.
- imerg_r_factor: mean 155 MJ mm ha⁻¹ h⁻¹, range 68-297.
- By year (mean over cells):

  | year | imerg_r_factor | imerg_max30min_amj (mm/h) |
  |---|---|---|
  | 2016 | 143 | 25.8 |
  | 2017 | 97 | 20.3 |
  | 2018 | 226 | 28.8 |
  | 2019 | 153 | 18.4 |
  | 2020 | 157 | 29.6 |

  2018 is the highest, which matches its record wet June.
- Correlation of imerg_r_factor with POWER prcp_amj across cell-years: 0.52.

**How to use these numbers.** Treat imerg_r_factor as a **relative between-year and between-cell storminess index, not an absolute R factor.** For scale, the published annual R factor for central Iowa is about 2,500-3,400 MJ mm ha⁻¹ h⁻¹ yr⁻¹, of which roughly 35-40% falls in AMJ. Ours is far lower for two reasons:
1. 0.1° half-hourly areal means damp peak intensity, so I30 is much lower than at a point gauge.
2. Only the top 6 days are counted.

The true AMJ maximum 30-min intensity may also fall on a day that was not sampled; in that case imerg_max30min_amj understates it.

## Caveats
- **Terrain:**
  - NASADEM/SRTM is a 1-arcsecond radar DSM with about 1-2 m of noise. Trees, buildings and road embankments are in the surface, and the depression filling reaches up to 55 m at embankments and dams.
  - Slope is computed on a DEM smoothed with σ = 1 px. Without smoothing the median slope was 4.3%, which is noise-inflated relative to the 3.0% after smoothing.
  - The DEM grid has a 6 km buffer around the tile. Even so, flow accumulation along the big rivers (Des Moines, Skunk, Iowa) is truncated where their basins extend beyond the buffer. This hardly matters for field points, whose median flowacc is 2 cells.
  - No 3DEP lidar was used.
- **Soils:**
  - Rasters were sampled at the 20 m overview with nearest-neighbour resampling, at the single pixel that contains the point. SSURGO polygons are mapped at about 1:12,000-1:24,000 scale, so 20 m sampling is enough.
  - Properties come from the dominant component only; minor components are ignored.
  - kwfact comes from the SDA string field, cast to float.
  - A few negative aws0_100 values (26 points, sentinel-like) were set to null.
- **POWER:** MERRA-2 cells (about 55 × 52 km) are coarse. Every point in a cell shares the same weather, so weather is a regional modifier, not a field-scale variable.
- **IMERG:** see the IMERG section above. The fields are partial: only 2016-2020, only the top-K days, and areal 0.1° intensities that underestimate point I30.
- **Not done:** NLDAS, SMAP and ECOSTRESS. They need an Earthdata login, which is not available.
