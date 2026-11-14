# sat module: MODIS vegetation stress + NEX-GDDP-CMIP6 2045 deltas

## Scripts (re-runnable; raw reads cached under data/raw/, cached files are skipped)
```
/home/user/venv-db/bin/python pipeline/sat_modis.py       # MOD13Q1 fetch (570 items, ~9 min cold) + modis_county_year
/home/user/venv-db/bin/python pipeline/sat_cropmask.py    # crop share per MODIS pixel from the cdl module's CDL 2016 lattice (~6 s)
/home/user/venv-db/bin/python pipeline/sat_modis.py --compute   # re-aggregate after the crop mask exists (~1 min)
/home/user/venv-db/bin/python pipeline/sat_cmip6.py       # NEX-GDDP-CMIP6 fetch (~600 files, ~3.5 h cold) + deltas
/home/user/venv-db/bin/python pipeline/sat_cmip6.py --compute   # deltas from the cache only (~1 min)
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

CMIP6_SECTION_PLACEHOLDER
