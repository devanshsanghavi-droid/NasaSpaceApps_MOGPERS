# Module `cdl`: field universe and crop history (`data/fields.parquet`)

## What was built
- `pipeline/cdl_common.py`: shared helpers. Gives the tile bbox in EPSG:5070 (600 m buffer, snapped to the CDL national 30 m grid, whose pixel edges fall at 15 m mod 30) and a clip-to-tile function.
- `pipeline/cdl_fetch_pc.py`: gets USDA CDL `cropland` for **2008-2021** from Planetary Computer (`usda-cdl`, query `usda_cdl:type=cropland`). It mosaics the 6 intersecting 90 km tiles per year onto one grid and writes `data/raw/cdl/cdl_<year>_tile.tif`. No resampling: the windows are integer-aligned, and the code asserts this.
- `pipeline/cdl_download_nass.py`: **PC has no CDL after 2021.** For **2022, 2023 and 2024** it downloads the official national 30 m CDL zips from USDA NASS (`https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip`, 1.7-2.1 GB each) with 10 parallel range requests. It then extracts the GeoTIFF, clips the tile window to `data/raw/cdl/cdl_<year>_tile.tif` and deletes the big zip and tif (pass `--keep` to keep them).
  - The CropScape `GetCDLFile` service was tried first and timed out after 90 s with no bytes.
  - Check that NASS and PC are on the same grid: the IoU of developed classes (121-124) between the 2021 (PC) and 2022 (NASS) clips is 0.999 at zero shift and 0.62 at a 1-pixel shift, so the two sources are pixel-aligned.
- `pipeline/cdl_fields.py`: samples every grid point and builds `data/fields.parquet`.
  - Uses the Census cartographic boundary counties 2023 1:500k (`data/raw/cdl/census/cb_2023_us_county_500k.zip`). If the zip is missing, the script downloads it from `https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip` (writes `.tmp`, then renames). It is byte-identical (same md5) to the copy the context module caches in `data/raw/census/`.
  - Prints the report. The last run's output is in `data/raw/cdl/fields_build.log`.

## Re-run
```
PY=".venv/bin/python"
"$PY" pipeline/cdl_fetch_pc.py         # ~1 min; returns at once (no network) if all 2008-2021 tiles are cached
"$PY" pipeline/cdl_download_nass.py    # ~5-7 min per year download + extract; skipped if cdl_<year>_tile.tif exists
"$PY" pipeline/cdl_fields.py           # ~10 s; downloads the Census county zip (~11 MB) if missing
```
Cache: `data/raw/cdl/cdl_2008_tile.tif` ... `cdl_2024_tile.tif`. These are uint8, EPSG:5070, 30 m, about 2 MB each.
- 2008-2021 (PC clips): 3843 rows x 3793 cols, top-left origin x=145155, y=2166315.
- 2022-2024 (NASS clips): 3844 rows x 3793 cols, top-left origin x=145155, y=2166345. That is one extra row on top.
- All rasters are on the same national 30 m grid. Sampling uses each raster's own transform, so the values are correct. Anyone stacking the rasters directly must **align them by transform, not by array index**.

## Columns (50,850 rows, one per grid point; key `field_id`)
| column | type | meaning |
|---|---|---|
| field_id | str | 'f' + 5-digit grid_id |
| grid_id | int32 | row*226 + col |
| row, col | int16 | grid indices (region.json) |
| x, y | float64 | UTM 15N (EPSG:32615) metres, grid point |
| lon, lat | float64 | WGS84 degrees |
| county_fips | string | 5-char state+county FIPS (e.g. '19169'); point-in-polygon on Census CB 2023 500k |
| county_name | string | county name (e.g. 'Story') |
| cdl_2008 .. cdl_2024 | Int16 | CDL class code of the 30 m pixel containing the point (no nulls; all 17 years fetched) |
| homog_2008 .. homog_2024 | float32 | share of the 3x3 pixel block (90 m) whose code equals the centre code (1/9 .. 1) |
| is_field | bool | see rule below |
| crop_seq_2016_2024 | str | 9 letters, one per year 2016..2024 |

**Letters:**
- C: corn. Codes 1, 12 sweet corn, 13 pop corn, 241 dbl corn/soy.
- S: soy. Codes 5, 239 dbl soy/cotton, 240 dbl soy/oats.
- W: wheat. Codes 22, 23, 24, plus double crops led by wheat: 26, 225, 236, 238.
- R: other row crops. Codes 2 cotton, 3 rice, 4 sorghum, 6 sunflower, 10 peanuts, 11 tobacco, 41 sugarbeets, 42 dry beans, 43 potatoes.
- O: oats and other small grains. Codes 21 barley, 25, 27 rye, 28 oats, 30 speltz, 205 triticale, plus double crops led by barley: 237, 254.
- H: hay or alfalfa. Codes 36, 37, 58.
- P: pasture or grass. Codes 59, 60, 62, 176.
- X: everything else, including 61 fallow, developed, water, forest and wetlands.

A double crop gets the letter of the crop named first.

**is_field rule:** in at least 7 of the 9 years 2016-2024, both of these hold **in the same year**:
- The letter is in {C, S, R} (corn, soy, other row crop), as the contract says. Small grains (O) and wheat (W) are not row crops, so they do not count as qualifying years. A field can still have up to 2 O/W years, and 145 fields do.
- The 3x3 homogeneity is at least 7/9.

Homogeneity compares **raw CDL codes**, as the contract column defines it ("share of 3x3 block equal to center"). A corn centre (1) next to sweet corn (12) or dbl corn/soy (241) counts as different. Those classes are very rare here, so the effect is negligible.

Change log (verifier fixes): the previous build counted {C, S, O, W} and tested crop years and homogeneous years separately. The new rule drops 85 points from is_field (26,408 -> 26,323) and adds none. 41 of the dropped points have O/W years; the other 44 failed the same-year requirement.

The task stated the threshold as "homog >= 0.78 (7 of 9 pixels)". 7/9 is 0.7778, so I implemented it as a count of at least 7 equal pixels, which matches the stated intent.

## Row counts and sanity stats
- **Grid points:** 50,850. **is_field = True:** 26,323 (51.8%).
- **Fields by county:**

  | County | Fields |
  |---|---|
  | Story | 3692 |
  | Boone | 3692 |
  | Jasper | 3202 |
  | Hamilton | 2939 |
  | Hardin | 2676 |
  | Marshall | 2615 |
  | Dallas | 2565 |
  | Polk | 1852 (urban Des Moines) |
  | Webster | 1345 |
  | Grundy | 781 |
  | Greene | 375 |
  | Madison | 214 |
  | Marion | 206 |
  | Warren | 169 |

  These are 14 counties. Edge counties are only partly inside the tile.
- **Rotation pattern (fields):**

  | Pattern | Fields |
  |---|---|
  | Strict corn-soy alternation (CSCSCSCSC / SCSCSCSCS) | 14,171 (53.8%) |
  | Corn-soy with one or more repeat years | 7,462 |
  | Continuous or mostly corn (at least 7 C) | 4,033 (426 are CCCCCCCCC) |
  | Includes hay / pasture | 313 |
  | Includes small grains / wheat (1-2 years) | 144 |
  | Other (one or two X years) | 168 |
| Includes other row crop | 8 |
  | Mostly soy | 24 |
- **Corn years per field, 2016-2024:**

  | Corn years | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
  |---|---|---|---|---|---|---|---|---|---|---|
  | Fields | 5 | 9 | 24 | 204 | 7696 | 10885 | 3423 | 2284 | 1367 | 426 |
- **Switching:** fields with at least one repeat year 2016-2024 (same crop twice in a row): 11,883.
  - Regime switch, meaning the same sequence holds both a run of 4 or more alternating years and a run of 3 or more years of the same crop: 2,928.
  - Rotation in 2016-2020 (no repeats), then at least one repeat in 2020-2024: 2,065.
  - At least one repeat in 2016-2020, then pure rotation in 2020-2024: 3,465.
- **Crop codes at field points, 2016-2024:** 98.7-99.9% of field-years are corn (1) or soy (5) in every year.
- **Mean 3x3 homogeneity:** 0.82-0.84 across all points and 0.95-0.985 on fields.
- **CDL classes at all points:** in 2016, 41% are corn and 26% soy. The rest are mainly grass/pasture (176), forest (141) and developed (121-123).

## Caveats
- **Source mix:** 2008-2021 come from Planetary Computer and 2022-2024 from the NASS national release. Both are the official CDL on the same national grid, but they are different release channels. Older CDL years on PC may predate later NASS re-releases; the codes are not re-harmonized.
- **Sample units:** a "field" is a 480 m grid sample inside a homogeneous block, not a field polygon. One real field can hold several samples, and samples are not independent. Downstream causal work should cluster or block spatially.
- **Repeat years:** CDL misclassification creates false repeat years, for example a single "CC" inside an alternating sequence. Some "switches" are classification noise. CDL accuracy for corn and soy in Iowa is high (about 95% and up). A stricter switch definition (2 or more consecutive repeats) is safer for treatment definitions.
- **Small grains:** small grains and wheat do not count as qualifying crop years (contract: corn/soy/other row crop). Only 144 fields have any O/W year, so an oats-in-rotation regime has almost no support, and an extended rotation with 3 or more small-grain years is excluded from is_field by design.
- **Mostly corn but not continuous:** 4,033 fields have 7 or more corn years, but only 426 are corn in all 9 years.
- **Edge points:** the county join is point-in-polygon on the 1:500k cartographic boundaries, so points within about 50 m of a county line may be assigned to the neighbouring county.
- **Not used:** CDL confidence layers (available 2017+) were not used.

## Provenance
- USDA NASS Cropland Data Layer 2008-2021: Microsoft Planetary Computer STAC `usda-cdl` (`usda_cdl:type=cropland`), https://planetarycomputer.microsoft.com/api/stac/v1
- USDA NASS Cropland Data Layer 2022-2024: https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip
- Counties: US Census Cartographic Boundary 2023 1:500k, https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip (cdl_fields.py downloads it automatically if missing)

## Deviations from contract
- Schema: none. File name, key, columns and types match CONTRACTS.md.
- The "homog >= 0.78" threshold is implemented as at least 7 of 9 pixels (7/9 = 0.7778).
- 2022-2024 come from NASS direct downloads because PC stops at 2021. The 2022-2024 clips have one extra top row; see Re-run.
- Double crops and sweet/pop corn take the letter of the crop named first.
