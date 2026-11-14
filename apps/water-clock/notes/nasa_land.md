# nasa (part B): land - USDA CDL, MODIS MOD16A3GF ET, HLS irrigation test

Owner files: `pipeline/nasa_cdl_common.py`, `pipeline/nasa_cdl_fetch.py`, `pipeline/nasa_cdl_county.py`, `pipeline/nasa_cdl_points.py`,
`pipeline/nasa_modis_et.py`, `pipeline/nasa_hls_irrigation.py`. Outputs in `data/processed/`: `cdl_county.parquet`,
`cdl_county_codes.parquet` (extra), `cdl_points.parquet`, `modis_et_county.parquet`, `hls_irrigation.parquet`,
`hls_irrigation_metrics.json` (extra). Raw caches go in `data/raw/{cdl,modis,hls,power_land}/` (gitignored).

Re-run order (about 10 minutes in total):
`nasa_cdl_fetch.py` (about 4 min) -> `nasa_cdl_county.py` -> `nasa_cdl_points.py` (needs `wimas_use.parquet`) -> `nasa_modis_et.py` (about 3 min)
-> `nasa_hls_irrigation.py` (about 2 min; needs `wimas_use.parquet` for labels).
Every number comes from a real download. Nothing was typed in.

Region: the 26 CONTRACTS.md counties. Polygons come from the Census `cb_2023_us_county_500k.zip` file through `nasa_common.region_counties()`.
The analysis grid is the native USDA CDL 30 m Albers grid (EPSG:5070), clipped to the county bounds plus 1 km (7,594 x 11,563 px).
County membership = the pixel centre falls inside the county polygon. The counties total 14.69 M acres, which matches the 59,444 km2 (14.7 M ac) region area.

## 1. CDL 2008-2024 -> `cdl_county.parquet`
- Sources:
  - 2008-2021: Microsoft Planetary Computer STAC `usda-cdl`, `usda_cdl:type=cropland`, 12 COG tiles per year (90 km) on
    `landcoverdata.blob.core.windows.net/usda-cdl/tiles/...`, signed with `planetary_computer`. Planetary Computer only has 2008-2021.
  - 2022-2024: USDA NASS national zips
    `https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/{2022,2023,2024}_30m_cdls.zip`.
    Only the byte range of the `.tif` member was downloaded (1.1-1.5 GB per year, parallel range requests). It was inflated and CRC-checked
    locally, the region window was clipped, and the national file was deleted.
- **Resolution: native 30 m, no overviews and no resampling.** acres = pixel count x 900 m2 / 4046.856 = **0.22239 ac per pixel**.
  The NASS CDL metadata notes that the early CDLs (2008-2009) relied partly on coarser AWiFS (56 m) imagery that was delivered on the 30 m grid,
  so the effective detail of those years is coarser.
- Columns:
  - `county_fips`, `county_name`, `gmd`, `year`, `crop`, `n_pixels`, `acres`.
  - `crop` is one of: corn (CDL codes 1, 12, 13), sorghum (4), winter_wheat (24), soybeans (5), cotton (2), alfalfa (36), fallow_idle (61),
    grass_pasture (62, 171, 176, 181), double_crop (26, 225, 226, 236-241, 254), other_crops (all other crop codes),
    shrubland (64, 152), developed, water_wetland, forest, barren, nodata.
  - The classes sum to the county area.
  - `cdl_county_codes.parquet` holds every raw CDL code per county-year, so the classes can be remapped later.
- Region totals in 1,000 acres:

  | Year | Corn | Sorghum | Winter wheat | Fallow/idle | Grass/pasture |
  |---|---|---|---|---|---|
  | 2008 | 1,705 | 1,074 | 2,797 | 2,545 | 5,479 |
  | 2012 | 2,004 | 890 | 3,159 | 2,303 | 5,322 |
  | 2019 | 3,111 (peak) | 1,075 | 2,692 | 1,848 | 4,431 |
  | 2023 | 2,336 | 1,750 | 2,483 | 2,218 | 4,287 |
  | 2024 | 2,675 | 1,251 | 2,641 | 1,875 | 5,107 |

  Soybeans 40-145k ac, alfalfa 150-190k ac, cotton <25k ac.
- Caveats:
  - **CDL does not separate irrigated from dryland.** NW Kansas (Thomas 300k ac corn in 2024, Sherman 217k) has a lot of dryland corn.
    Irrigated acreage has to come from WIMAS (`acres_irrigated`) or NASS irrigated practice.
  - CDL per-class accuracy in Kansas is typically high for corn and wheat and lower for sorghum, fallow and grass.
    The grass/pasture vs fallow and shrubland split is the least reliable.
  - The jump in grass/pasture in 2024 (+0.8 M ac) together with a fall in fallow/idle is at least partly a classification change, not only land use.
  - No NASS county comparison was done here: `nass_county.parquet` (econ) did not exist yet when this was written.

## 2. CDL at WIMAS points of diversion -> `cdl_points.parquet`
- Input: `wimas_use.parquet` (pumping module), 23,454 unique `pdiv_id` across all 26 counties.
  It was present when this ran, so the script was run; nothing is pending.
  If the pumping module rewrites `wimas_use.parquet`, re-run `python3 pipeline/nasa_cdl_points.py` (about 7 s).
- 398,718 rows (23,454 x 17 years). Columns:
  - `pdiv_id`, `year`
  - `cdl_code`, `cdl_class`, `cdl_name`: the pixel at the point.
  - `cdl_mode_code_250m`, `cdl_mode_class_250m`, `mode_frac_250m`: the most common non-zero code in a 250 m radius disk, and its share.
  - lon/lat are not repeated. Join to `wimas_use` on `pdiv_id`.
  - 2 points fall outside the grid (NaN).
- Check against the crop reported in WIMAS (IRR rows with `crop_group` corn/wheat/sorghum/soybeans/alfalfa, n = 114,315 point-years):
  - The pixel at the point agrees 48% of the time.
  - **The 250 m mode agrees 66% of the time**: corn 69%, alfalfa 73%, wheat 57%, sorghum 44%, soybeans 35%.
  - The point of diversion is the well, which often sits at a field edge or corner, and one water right can serve several fields. **Use the 250 m mode.**

## 3. MODIS MOD16A3GF v061 annual ET -> `modis_et_county.parquet`
- Source: Planetary Computer STAC `modis-16A3GF-061`, asset `ET_500m` (COGs on `modiseuwest.blob.core.windows.net/modis-061-cogs/`).
  Terra (`MOD16A3GF`) items only, tiles h09v05, h10v05 and h10v04, years **2001-2025** (2025 is published as year-end gap-filled).
- Units:
  - Raw uint16, scale 0.1 -> kg m-2 yr-1 = mm/yr. Converted to inches with mm / 25.4. `modis_et_mm` is kept too.
  - 65529-65535 are fill or non-vegetated codes (65535 fill, 65534 water, 65533 barren, 65532 snow/ice, 65531 wetland, 65530 urban,
    65529 unclassified). They are excluded and counted in `n_pix_fill`: 9,925 fill vs 6.96 M valid pixel-years.
- Crop classes:
  - Every 30 m CDL pixel is linked to its 500 m MODIS cell by a nearest warp of a MODIS cell-id raster onto the CDL grid.
    This gives exact CDL class fractions per MODIS cell per year (2008-2024).
  - A MODIS cell belongs to the county that holds most of its 30 m pixels.
- Columns:
  - `county_fips`, `county_name`, `gmd`, `year`, `modis_et_in`, `modis_et_mm`, `n_pix`, `n_pix_fill`.
  - For each class in corn, winter_wheat, sorghum, soybeans, alfalfa, grass_pasture, fallow_idle and shrubland:
    - `et_<cls>_in`: area-weighted by class fraction.
    - `et_<cls>_pure_in`: mean over MODIS cells that are at least 75% that class (needs at least 3 cells).
    - `n_<cls>_pure`: the number of those cells.
  - Crop columns are NaN for 2001-2007 and 2025 (no CDL).
  - Region mean pure-cell counts per year: corn 13,052, winter wheat 14,374, sorghum 4,832, grass 43,097, fallow 9,992, soybeans 202, alfalfa 736.
- Results, means over county-years 2008-2024 (inches/yr):

  | Measure | ET (in/yr) |
  |---|---|
  | All pixels | 12.7 |
  | Corn (area-weighted) | 14.4 |
  | Corn (pure cells) | 15.3 |
  | Soybeans (pure) | 16.0 |
  | Alfalfa (pure) | 18.4 |
  | Sorghum (pure) | 14.0 |
  | Winter wheat (pure) | 12.7 |
  | Grass/pasture (pure) | 12.2 |
  | Fallow/idle (pure) | 10.1 |

  Corn minus grass (pure cells, by county-year): median +2.8 in, IQR 2.0-3.8.
  Dry years are low across the board: 2011 9.0 in, 2012 9.0 in, 2022 10.0 in region mean. 2019 is high at 16.0 in.
- **Caveat (important):**
  - MOD16 computes ET from MODIS LAI/FPAR/albedo and reanalysis meteorology with a Penman-Monteith scheme. It has no irrigation input,
    it is known to **underestimate ET of irrigated cropland in semi-arid regions**, and it lowers ET in drought years through its VPD and
    soil constraints even where fields are irrigated.
  - Mixed 500 m cells (a center pivot is about 53 ha, a MODIS cell about 21 ha) blur the contrasts too.
  - Use MODIS as a **relative** crop signal (corn > sorghum > wheat > grass > fallow, and inter-annual anomalies), not as absolute
    irrigated-corn consumptive use. Irrigated corn ET in SW Kansas is commonly reported at about 22-26 in.
  - For the rotation engine, POWER FAO-56 ET0 x crop coefficients is the better absolute basis, with MODIS as a cross-check.
  - OpenET (field scale) is blocked because there is no API key (already in BLOCKERS.md).

## 4. HLS dry-spell irrigation detection -> `hls_irrigation.parquet`, `hls_irrigation_metrics.json`
- Focus counties: **Haskell (20081)**, the requested county, and **Finney (20055)**.
  Finney was added because Haskell's wells are so dense that dryland candidates there are very few (below).
  Summers 2022 and 2023.
- Dry spell: NASA POWER daily `PRECTOTCORR` at the county centroid
  (`https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR&community=AG&...`).
  The dry spell is the 14-day window in Jul 1 - Aug 31 with the least rain. Scenes are taken from window start + 5 d to window end + 3 d.

  | County, year | Dry spell | Rain in spell | Jul-Aug total |
  |---|---|---|---|
  | Haskell 2022 | Jul 7-20 | 2.3 mm | 104 mm |
  | Haskell 2023 | Aug 14-27 | 0.8 mm | 207 mm |
  | Finney 2022 | Jul 7-20 | 2.7 mm | 119 mm |
  | Finney 2023 | Aug 14-27 | 1.5 mm | 186 mm |

- HLS v2: Planetary Computer `hls2-l30` and `hls2-s30` (blob `hls2euwest`), cloud cover < 60%, MGRS tiles T14SLG (Haskell) and T14SLG + T14SLH (Finney).
  - Scenes used: 33 in total. Haskell 3 + 7, Finney 9 + 14. Every scene and its clear-point count is listed in the metrics json.
  - Red/NIR (L30 B04/B05, S30 B04/B8A), scale 1e-4, fill -9999.
  - Clear = Fmask bits 1-4 all zero and Fmask != 255.
  - Windowed reads at native 30 m over the county only (no overviews needed).
  - NDVI per point = **maximum over clear observations** in the window (`ndvi_max`). `ndvi_median` and `n_obs` are kept too.
    In Haskell 2022, 18 points had no clear observation.
- Sample points: field-interior 30 m CDL pixels (3x3 same class) of corn, soybeans and sorghum, from the CDL of the same year.
- Labels from WIMAS:
  - **Irrigated**: an IRR point of diversion that reported water (`af_reported` > 0) that year lies within 800 m.
  - **Dryland**: no WIMAS point of diversion of any use or year lies within 1,600 m.
  - Points 800-1,600 m from a well are ambiguous and get no label.
  - In Haskell, 0.1-0.2% of field-interior corn pixels (and about 1% of sorghum pixels) are more than 1.6 km from any well.
    Haskell 2022 had 240,120 irrigated-labelled vs 427 dryland-labelled corn pixels.
    In Finney the dryland-labelled share is about 10% for corn and 47-50% for sorghum.
  - So sampling is **stratified**: per county, crop and year up to 75 irrigated-labelled + 75 dryland-labelled pixels, plus 50 unstratified
    `random` pixels (`stratum` column). Only the stratified points are used for accuracy.
  - There are no dryland soybean candidates.
  - The dryland samples come from few places: in Haskell they fall in only 21 distinct 1 km cells per year, in Finney 137-141.
- Threshold irrigated := `ndvi_max > t`. t was chosen on a random half (maximising balanced accuracy) and tested on the other half
  (`irrigated_pred` uses the pooled t = 0.62).

  | Test set | t | n test (irrigated) | Accuracy | Kappa | Median NDVI, irrigated vs dryland |
  |---|---|---|---|---|---|
  | **Corn only, both counties and years** | 0.65 | 299 (151) | **0.92** | **0.83** | 0.85 vs 0.38 |
  | Corn 2022 | 0.56 | 149 | 0.91 | 0.82 | |
  | Corn 2023 | 0.60 | 150 | 0.92 | 0.84 | |
  | All crops pooled | 0.62 | 742 (441) | 0.76 | 0.51 | 0.83 vs 0.46 |
  | Haskell, all crops | 0.79 | 367 | 0.73 | 0.48 | |
  | Finney, all crops | 0.56 | 375 | 0.76 | 0.49 | |

- Interpretation:
  - **Dry-spell HLS NDVI separates irrigated from dryland corn well** (kappa about 0.83).
  - Sorghum is the main source of error. It is planted in June, so in the early-July 2022 window its canopy is still open (NDVI 0.3-0.5 for
    both labels). Also, many "irrigated-labelled" sorghum pixels are probably dryland sorghum next to irrigated corn on the same well's land.
    In Haskell 2022 the median NDVI of irrigated-labelled sorghum (0.41) was below dryland (0.55).
  - In the random sample the predicted irrigated share of corn is 62-96% and of soybeans 88-100%.
- Caveats:
  - Labels are proximity proxies, not field boundaries.
  - Stratified, balanced evaluation does not equal accuracy at real prevalence.
  - The dryland samples are spatially clustered, which is optimistic, especially in Haskell.
  - Only two summers and two counties.
  - The thresholds differ between years (0.56-0.84) because the dry-spell timing changes crop stage, so a single fixed NDVI threshold should not be
    transferred blindly.

## Failures / blockers
- None blocking for this module.
- Planetary Computer `usda-cdl` stops at 2021. 2022-2024 were filled from the NASS national zips (www.nass.usda.gov), so this is not a blocker.
- OpenET (field-scale ET) needs an API key. It is already listed in BLOCKERS.md; MODIS is used instead.
