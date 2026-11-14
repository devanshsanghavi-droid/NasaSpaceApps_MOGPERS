# Module `cdl`: crop history, soils, terrain

Scripts (run in order, each re-runnable and cached):
```
python3 pipeline/p05_cdl_fetch.py    # ~8 min cold (4 NASS zips + 6 PC years); --check re-prints grid/IoU checks
python3 pipeline/p06_cdl_shares.py   # ~1 min
python3 pipeline/p07_soils_terrain.py  # ~2 min cold (gNATSGO overview, SDA, 16 NASADEM tiles)
```
Peak memory: p06 1.3 GB, p07 1.1 GB (row strips of 1200 px). Network: ≤ 6 threads.

## Raw rasters (data/raw/, gitignored) — reusable by other modules
| File | Content |
|---|---|
| `cdl/cdl_<year>_basins.tif`, 2016-2025 | USDA CDL class codes, uint8, nodata 0, EPSG:5070, 30 m, deflate. **All 10 years share one grid**: origin x=-10485, y=2364945 (top-left), 7059 cols × 10449 rows (211.8 × 313.5 km) = union bbox of both basins + 1.5 km, snapped to the CDL national grid (pixel edges at 15 m mod 30). Stack by array index safely. |
| `cdl/DONE_<year>` | empty sentinel, written after the year's clip is complete |
| `cdl/rowcrop_years_2016_2025.tif` | uint8, number of years (0-10) the pixel is row crop (letters C/S/R). **Row-crop pixel = count ≥ 6** (majority of years) |
| `cdl/huc12_index_30m.tif` | int16, index into the huc12 list sorted ascending (-1 = outside both basins); pixel-centre rasterization |
| `soils/mukey_90m.tif` | gNATSGO map-unit key, int32, nodata 0, EPSG:5070 90 m grid nesting the CDL grid (90 m cell (r,c) = CDL rows 3r..3r+2, cols 3c..3c+2), 3483 × 2353 |
| `terrain/slope_30m.tif`, `terrain/slope_90m.tif` | slope percent (100·tanβ), float32, CDL 30 m grid / 3×3 block mean on the 90 m grid |
| `soils/sda/components.parquet` | all SDA components (6,394 rows) of the 2,103 mukeys, with their surface horizon |

## data/processed/cdl_huc12_year.parquet — 2,900 rows (290 HUC-12 × 10 years), key (huc12, year)
## data/processed/cdl_basin_year.parquet — 20 rows (2 basins × 10 years), key (basin, year)
Columns (both files; huc12 file also carries `basin`): shares of area (0-1, float32):
`corn`, `soy`, `row_crop` (= corn + soy + other_row), `small_grain`, `hay`, `grass_pasture`, `forest`, `developed`,
`water_wetland`, `other_row`, `other` (remainder: fallow, shrub, barren, specialty crops…); `cropland_km2`
(all cultivated NASS crop codes 1-58, 61 fallow, 66-80, 204-254; excludes grass/pasture), `area_km2` (pixel area).
Area = pixels whose centre lies in the HUC-12 polygon (sums to 16,225 km² Des Moines, 9,004 km² Raccoon, matching
huc12.parquet). No nulls; no nodata pixels inside the basins.

Class groups (crop letters as in shared notes/cdl.md; double crops take the first-named crop):
- corn (C) 1, 12, 13, 241 · soy (S) 5, 239, 240 · other_row (R) 2, 3, 4, 6, 10, 11, 41, 42, 43
- small_grain = W (22, 23, 24, 26, 225, 236, 238) + O (21, 25, 27, 28, 30, 205, 237, 254) · hay (H) 36, 37, 58
- grass_pasture (P) 59, 60, 62, 176 · forest 63, 141, 142, 143 · developed 82, 121-124 · water_wetland 83, 87, 92, 111, 190, 195
- Letter lookup for other modules: `p06_cdl_shares.letter_lut()` (uint8 code → letter, X = everything else).

### Sanity stats
| basin | corn (mean, range) | soy | row crop | grass/pasture | developed |
|---|---|---|---|---|---|
| raccoon | 0.428 (0.406-0.459) | 0.328 (0.300-0.348) | **0.756 (0.741-0.768)** | 0.104 | 0.059 |
| desmoines | 0.438 (0.425-0.467) | 0.339 (0.314-0.355) | **0.777 (0.756-0.788)** | 0.068 | 0.064 |

- Corn peaks in 2016 (both basins); soy ≥ 0.33 from 2021 on. Row crop is ~75-78% of both basins every year.
- HUC-12 mean row-crop share: median 0.83; min 0.03 (071000041003 Saylor Creek-Des Moines River, 76% developed),
  then 0.20-0.24 (Raccoon HUC-12s 071000070701 Beaver Creek, 071000070403 Mason Creek), max 0.92.
- 68.4% of basin pixels are row crop in all 10 years; 77.0% in ≥ 6 years (row-crop pixels).
- Grass/pasture jumps in 2021+ in the Raccoon (0.09 → 0.12) at the PC→NASS / CDL-version boundary, while
  developed drops in 2019; these are partly CDL classification/version changes, not only land-use change.

### Grid check (PC 2016-2021 vs NASS 2022-2025)
`aligned_window()` asserts integer pixel alignment for every source (NASS national origins 2022-24: (-2356095,
3172605); 2025 has a larger national extent, origin (-2417835, 3321225); all on 15 mod 30). Developed-class
(121-124) IoU 2021 (PC) vs 2022 (NASS): **0.980 at zero shift vs 0.473 at any 1-pixel shift** → pixel-aligned.

## data/processed/soils_huc12.parquet — 290 rows, key huc12
All shares are of **row-crop area** (30 m row-crop pixels; mukey looked up from the nesting 90 m cell; slope at 30 m).
| column | meaning |
|---|---|
| huc12, basin | |
| poorly_drained_share | dominant-component drainagecl ∈ {Poorly drained, Very poorly drained} |
| somewhat_poorly_share | dominant-component drainagecl = Somewhat poorly drained |
| hydgrp_D_share | dominant-component hydgrp ∈ {D, A/D, B/D, C/D} — **dual groups included as "wet, usually tile-drained"** (the dual group's D applies in the undrained state). Almost all of it is C/D and B/D |
| hydgrp_D_only_share | hydgrp = D only (strict) |
| poorly_drained_share_comp | robustness: comppct_r-weighted share of all components that are poorly/very poorly drained |
| mean_slope_pct | mean NASADEM slope (%) over row-crop pixels |
| kwfact_mean, om_r_mean | mean surface-horizon K factor and organic matter (%) of the dominant component |
| rowcrop_km2, rowcrop_frac | row-crop pixel area and its fraction of the HUC-12 |
| soil_known_frac | fraction of row-crop pixels whose mukey has a drainage class (min 0.965, mean 0.999) |
| mean_slope_pct_all | mean slope over all pixels (context for low-row-crop HUC-12s) |

### Sanity stats (row-crop-area-weighted)
| basin | row-crop km² | poorly drained | (comp-weighted) | somewhat poorly | hydgrp D incl. dual | D only | slope % |
|---|---|---|---|---|---|---|---|
| raccoon | 6,768 | **0.439** | 0.443 | 0.180 | 0.619 | 0.006 | 2.89 |
| desmoines | 12,667 | **0.516** | 0.529 | 0.206 | 0.724 | 0.009 | 1.94 |

- HUC-12 range: poorly_drained_share 0.05-0.76 (Raccoon median 0.40, Des Moines 0.52); slope 1.3-5.9 %.
  Des Moines Lobe (flat, pothole) HUC-12s are wettest and flattest; the lower Raccoon (loess/drift hills) is steeper and better drained, as expected.
- Drainage classes of all row-crop pixels: poorly 43.3%, somewhat poorly 19.7%, moderately well 15.2%,
  well 15.2%, very poorly 5.6%, somewhat excessively/excessively 1.0%, unknown 0.1%.

## data/processed/soils_mukey.parquet — 2,099 rows, key mukey
mukey (int64), muname, compname, comppct_r, drainagecl, hydgrp, kwfact, om_r, slope_r (%, representative slope),
poorly_frac_comp, somewhat_frac_comp, hydgrp_D_frac_comp (comppct-weighted across all components).
Dominant component = max comppct_r (ties → lowest cokey); surface horizon = min hzdept_r. 152 mukeys have no
drainagecl (water, urban land, pits, etc.); 161 no hydgrp. To look up a location: sample `soils/mukey_90m.tif`, join here.

## Method details
- **CDL 2022-2025**: NASS national zips downloaded with 6 parallel HTTP range requests (~30 s each), tif extracted,
  integer window read with rasterio, zip and national tif deleted immediately (one national file at a time).
- **CDL 2016-2021**: PC `usda-cdl`, `usda_cdl:type=cropland`, 15 tiles per year mosaicked (first non-zero wins), no resampling.
- **gNATSGO mukey**: PC `gnatsgo-rasters` (6 tiles, 10 m, ESRI:102039 = same Albers parameters as EPSG:5070),
  warped nearest onto the 90 m grid; GDAL reads the 8× (80 m) overview. Check vs native 10 m at 40 random points:
  70% identical mukey (expected given 90 m cells vs small SSURGO polygons; shares over thousands of cells are robust).
- **SDA**: `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest`, SQL joining mapunit, component, top chorizon;
  batches of 300 mukeys, 4 threads; responses cached in data/raw/soils/sda/. 2,099 of 2,103 mukeys returned.
- **Slope**: 16 NASADEM 1-arcsec tiles (PC `nasadem`) bilinear to the 30 m CDL grid, Gaussian σ = 1 px (damps
  SRTM noise, as in shared notes/conf.md), Horn 3×3 slope, computed in strips with an 8-row halo.

## Caveats
- CDL is a classification (Iowa corn/soy accuracy ≈ 95%+); 2016-2021 come from PC and 2022-2025 from NASS
  releases — same grid and legend, not re-harmonized. Class-version shifts (grass/pasture, developed) appear at year boundaries.
- Soil attributes are dominant-component only (the comp-weighted poorly share differs by ≤ 0.013 at basin level).
- Drainage class describes natural drainage; most poorly drained Iowa row-crop land is artificially tile-drained,
  which is exactly why it matters for nitrate delivery. No tile-drainage map is used.
- 90 m mukey sampling loses small inclusions; NASADEM is a radar DSM (≈ 1-2 m noise, trees/embankments), so slope
  is smoothed and best read as relative between HUC-12s.

## Provenance
- USDA NASS CDL 2022-2025: `https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip`
- USDA NASS CDL 2016-2021: Planetary Computer STAC `usda-cdl`, https://planetarycomputer.microsoft.com/api/stac/v1
- gNATSGO rasters (USDA NRCS): Planetary Computer `gnatsgo-rasters`
- SSURGO tabular via USDA Soil Data Access: https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest
- NASA NASADEM (SRTM reprocessed) 1 arcsec: Planetary Computer `nasadem`

## Deviations from contract
- Extra columns: `basin`, `other_row`, `other`, `area_km2` in CDL tables; `hydgrp_D_only_share`,
  `poorly_drained_share_comp`, `kwfact_mean`, `om_r_mean`, `rowcrop_km2`, `rowcrop_frac`, `soil_known_frac`,
  `mean_slope_pct_all`, `basin` in soils_huc12. Contract columns are unchanged.
- `hydgrp_D_share` includes A/D, B/D, C/D (strict version in `hydgrp_D_only_share`).
- Contract lists these files under the `cover` owner; this `cdl` module produced them as assigned.
- No blockers: every source worked on the first try (nothing added to BLOCKERS.md).
