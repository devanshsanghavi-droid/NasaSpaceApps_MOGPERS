# Module `cdl`: county crop-rotation diversity from the USDA Cropland Data Layer (2008-2024)

## Outputs
| file | key | rows | years |
|---|---|---|---|
| `data/processed/cdl_county_year.parquet` | (fips, year) | 8,671 (667 counties x 13 window-end years) | window-end years 2012-2024 (window y-4..y) |
| `data/processed/cdl_county_static.parquet` | fips | 667 | whole record 2008-2024 (17 years) |
| `data/processed/cdl_focus_fields.parquet` | id | 1,223 | 2008-2024, Plymouth County IA (19149) |
| `web/data/focus_fields.json` | - | 1,223 fields | same as above |

No 2011 window: 2007 was not used (2008 is the first year with CONUS-wide CDL).

## Data sources
- **2008-2021**: Microsoft Planetary Computer STAC `usda-cdl`, `usda_cdl:type = cropland`
  (https://planetarycomputer.microsoft.com/api/stac/v1). PC has **only 2008-2021** (360 tiles per year in the search
  bbox; 202 tiles per year touch the 7 states). Tiles are 3000 x 3000 px, 30 m, EPSG:5070, on the CDL national grid.
- **2022-2024**: not on PC. Official USDA NASS national 30 m release
  `https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip`.
  Only the `.tif` member is fetched (HTTP range requests; the `.ovr` member is skipped), inflated locally (CRC checked),
  sampled, clipped for the focus county, then deleted. (A 2025 CDL zip also exists on NASS; not used, the contract stops at 2024.)
- **Grid alignment PC vs NASS**: in Plymouth County, the IoU of stable non-crop classes (developed 121-124, water 111,
  forest 141) between 2021 (PC) and 2022 (NASS) is 0.93 at zero shift vs 0.48 at a 1-pixel shift, so both sources
  are on the same pixel grid.
- **Counties**: US Census cartographic boundary 2023 1:500k
  (https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip, cached in `data/raw/census/`), 667 counties.

## Method
1. **Fixed sampling lattice** (`pipeline/cdl_common.py`): one point every **240 m** (8 CDL pixels) in EPSG:5070, at
   multiples of 240 m. Every point is exactly the centre of a CDL 30 m pixel (CDL pixel edges are at 15 m mod 30).
   The lattice is 6,159 x 5,845. **22,637,578 points** fall inside the 667 counties (one point per 5.76 ha). Each
   point is assigned to the county polygon that contains it (rasterised with the cell centre at the lattice point).
   The same pixels are read every year, so per-point crop sequences are valid.
2. **No overviews.** The PC COG overviews (2, 4, 8) are majority/mode-resampled: an overview value is always one of
   its 2x2 block values but matches any fixed pixel offset only 85-96% of the time. So every tile is read at full 30 m
   resolution and the lattice pixels are picked out exactly (`pipeline/cdl_pc_fetch.py`). The NASS national rasters are
   read at full resolution in 1024-row strips (`pipeline/cdl_nass_fetch.py`).
3. **Classes**: CDL code -> class (table below), per point and year.
4. **Cropland pixel**: a point counts in a 5-year window if it is in a cropland class (C, S, W, O, A, G, R, F) in >= 3
   of the 5 years; for the whole record, >= 9 of the 17 years. Pasture/grass (P) years are not cropland years, but a
   cropland pixel may have up to 2 (window) or 8 (record) P years, and those count as a perennial phase.
5. **Per-pixel metrics** (`pipeline/cdl_metrics.py`), then the mean over the county's cropland pixels:
   - `div_shannon_5y`: Shannon entropy (natural log) of the class frequencies over the window years that are in a
     diversity class. Diversity classes are C, S, W, O, G, R and one merged perennial class (A + P). Fallow (F) and
     non-crop (X) years are left out. Example: C-S alternation over 5 years = 0.673; one crop = 0.
   - `n_crops_5y`: number of distinct diversity classes.
   - `share_cont_corn`: corn in >= 3 consecutive years of the window.
   - `share_cs_only`: the diversity classes present are exactly {C, S} (fallow/non-crop years are ignored).
   - `share_3plus`: >= 3 distinct diversity classes.
   - `share_small_grain_5y`: W or O in at least one window year.
   - `share_perennial_5y`: A or P in at least one window year.
   - Crop shares of the window-end year among the window's cropland pixels: `corn_share`, `soy_share`, `wheat_share`,
     `sorghum_share`, `hay_alfalfa_share` (A only), `other_share` = 1 - those five (O, P, R, F, X). They sum to 1.
   - Extra (not in the contract): `perennial_share` (A + P that year; robust to the 2024 hay -> grassland relabel, see
     caveats) and rotation-class shares `rc_with_perennial`, `rc_continuous_corn`, `rc_corn_soy`, `rc_3plus`,
     `rc_other` (same rules as the focus-field rotation_class below; they sum to 1).
6. **Static** (`cdl_county_static.parquet`): the same per-pixel metrics computed over all 17 years (2008-2024) with
   **the same column names** as `cdl_county_year` (so `div_shannon_5y` there is the 17-year entropy, `share_cont_corn`
   is "corn >= 3 consecutive years anywhere in 2008-2024", and the crop shares are 17-year means). Extra columns:
   `n_pts` (all lattice points in the county), `cropland_frac` = n_px / n_pts, `years` = "2008-2024", `perennial_share`.
   These record-long values are much larger than the 5-year ones (mean n_crops 2.85, share_3plus 0.52) and are not
   comparable with the window values.
7. **Small samples**: rows with `n_px < 20` have every metric set to NaN (88 county-year rows, 16 counties: mostly
   Ozark counties in southern MO in some windows, plus 27031 Cook MN, 27075 Lake MN, 27123 Ramsey MN and 29510
   St. Louis city, which have almost no cropland; 6 static rows: 27031, 27075, 27123, 29153, 29213, 29510).

### Crop class grouping (CDL code -> class; internal id -> letter in `seq`)
| class | letter | CDL codes |
|---|---|---|
| C corn | C | 1 corn, 12 sweet corn, 13 pop/orn corn, 241 dbl corn/soy |
| S soybeans | S | 5 soybeans, 239 dbl soy/cotton, 240 dbl soy/oats |
| W wheat | W | 22 durum, 23 spring, 24 winter wheat; dbl crops led by wheat: 26 (WinWht/Soy), 225 (WinWht/Corn), 236 (WinWht/Sorghum), 238 (WinWht/Cotton) |
| O other small grains | O | 21 barley, 25 other small grains, 27 rye, 28 oats, 30 speltz, 205 triticale; dbl crops led by oats/barley: 226, 235, 237, 254 |
| A alfalfa/hay | A | 36 alfalfa, 37 other hay/non-alfalfa, 58 clover/wildflowers |
| G sorghum | G | 4 |
| P pasture/grass | P | 59 sod/grass seed, 60 switchgrass, 62 pasture/grass, 171 grassland herbaceous, 176 grassland/pasture, 181 pasture/hay |
| R other crops | X | every other agricultural code in 1-60, 66-80, 200-255 (cotton, rice, sunflower, millet, canola, flax, sugarbeets, dry beans, potatoes, peas, vegetables, orchards, ...) |
| F fallow/idle cropland | X | 61 |
| X non-crop | X | 0 background, 63-65, 81-195 (developed, water, forest, shrub, wetlands, barren, clouds) |

A double crop takes the class of the crop named first. R and F are cropland classes and kept apart internally, but the
contract's letter set has no letter for them, so they are written as `X` in `seq`. The parquet column `seq_detail` keeps
the internal letters (R, F distinct).

### Focus fields: Plymouth County, IA (19149) (`pipeline/cdl_focus.py`)
- Full 30 m CDL clip of the county (+300 m buffer) for all 17 years: `data/raw/cdl/focus/cdl_<year>_19149.tif`.
- Candidates on a 900 m grid (densified to 600/450/300 m only if < 300 qualify; not needed). A candidate is kept if its
  whole 5x5 block (150 m x 150 m) is inside the county and, in >= 14 of the 17 years, >= 22 of the 25 block pixels share
  the centre's class AND the centre is a cropland class. 2,778 candidates -> **1,223 field samples**.
- `rotation_class` (window 2020-2024; first rule that applies): any A/P year -> "with perennial"; corn >= 3 consecutive
  years -> "continuous corn"; only C and S, both present -> "corn-soy"; >= 3 distinct classes -> "3+ crop"; else "other".
  Result: corn-soy 1,123, continuous corn 87, with perennial 10, 3+ crop 3. Over 2008-2024
  (`rotation_class_2008_2024`): corn-soy 939, continuous corn 221, with perennial 58, 3+ crop 5.
- Parquet columns: id, fips, lon, lat (WGS84, 5 decimals), x_5070, y_5070, seq (17 letters 2008..2024), seq_detail,
  rotation_class, div_shannon_2020_2024, n_crops_2020_2024, rotation_class_2008_2024, div_shannon_2008_2024,
  n_crops_2008_2024, n_homog_crop_years.
- JSON: `{county:{fips:"19149", name:"Plymouth County, IA"}, years:[2008..2024], fields:[{id, lon, lat, seq,
  rotation_class, div5, ncrop5}]}` (div5 rounded to 3 decimals), 152 KB.

## Sanity checks
State means of the 2022 window (2018-2022), weighted by n_px:

| | IA | IL | KS | MN | MO | NE | SD |
|---|---|---|---|---|---|---|---|
| corn_share | 0.528 | 0.479 | 0.222 | 0.404 | 0.273 | 0.514 | 0.320 |
| soy_share | 0.418 | 0.471 | 0.176 | 0.376 | 0.485 | 0.297 | 0.285 |
| wheat_share | 0.001 | 0.022 | 0.277 | 0.062 | 0.038 | 0.048 | 0.085 |
| sorghum_share | 0.000 | 0.000 | 0.125 | 0.000 | 0.001 | 0.013 | 0.015 |
| share_cs_only | 0.861 | 0.839 | 0.141 | 0.580 | 0.516 | 0.613 | 0.440 |
| share_3plus | 0.059 | 0.093 | 0.293 | 0.224 | 0.142 | 0.125 | 0.279 |
| share_cont_corn | 0.163 | 0.090 | 0.072 | 0.091 | 0.022 | 0.220 | 0.027 |
| share_small_grain_5y | 0.018 | 0.082 | 0.707 | 0.216 | 0.120 | 0.175 | 0.293 |
| div_shannon_5y | 0.633 | 0.655 | 0.652 | 0.692 | 0.540 | 0.599 | 0.653 |

- IA/IL are corn-soy (84-86% of cropland pixels are C/S only) with low share_3plus (6-9%). KS and SD have far more wheat,
  sorghum and 3+ crop rotations. NE has the most continuous corn (irrigated corn), as expected.
- Iowa county corn_share in 2022: median 0.53, 10th-90th percentile 0.41-0.58, state 0.53.
- **Against NASS county planted acres** (`nass_county_year.parquet`, geo module): corn / (corn + soy + wheat + sorghum)
  from CDL vs NASS, counties with NASS corn and soy published: 2012 n = 520, r = 0.985, MAE 0.017; 2022 n = 477,
  r = 0.982, MAE 0.014, bias -0.003.
- Note: Shannon entropy rewards evenness, so a perfect C-S alternation (0.673) scores higher than a 3-crop rotation
  dominated by one crop. That is why the IA/IL mean div_shannon_5y is close to KS/SD even though share_3plus is much
  lower. Use `share_3plus` / `n_crops_5y` for "how many crops" and `div_shannon_5y` for the contract's entropy.
- 2019 shows a fallow/idle (F) spike (9% of cropland pixels vs ~3% in other years): this is the 2019 prevented-planting
  year, a real signal.

## Caveats
- **CDL 2024 relabels hay as grassland.** Among persistent cropland pixels, code 37 (other hay) falls from 51k to 5k
  sample points from 2023 to 2024 and 176 (grassland/pasture) rises from 63k to 204k. So `hay_alfalfa_share` collapses in
  2024 (e.g. SD 0.16 -> 0.05, MO 0.10 -> 0.003) and `perennial_share` (A + P) is the stable column. A and P are merged
  into one class for the diversity metrics to limit the effect, but the 2020-2024 window still shows a small jump in
  diversity in grass-heavy states (div_shannon_5y 2023 -> 2024 window: KS 0.662 -> 0.688, SD 0.653 -> 0.688,
  MO 0.553 -> 0.586; IA 0.632 -> 0.641). Treat the 2024 window with care; the 2023 window (2019-2023) is a cleaner
  "current" value.
- **Early years (2008-2010)** label ~10% of persistent cropland pixels as grass (62/171/176) vs 1-2% after 2015, and
  2008-2012 windows have higher share_3plus. Part of the 2012-2016 decline in diversity is classification, not practice.
- **Sample units**: a lattice point is a 30 m pixel, not a field. CDL misclassification adds false class changes (e.g. a
  single "CC" inside an alternation), so metrics carry some classification noise. CDL accuracy for corn and soy in the
  Corn Belt is high (~95%+), much lower for hay/pasture/grass.
- **Source mix**: 2008-2021 from PC, 2022-2024 from the NASS release. Same product and grid, but PC copies of older
  years may predate later NASS re-releases; codes are not re-harmonised.
- **Focus fields** are biased toward large homogeneous fields (5x5 block rule plus >= 14 cropland years), so perennial
  and diverse fields are under-represented (10 "with perennial" in 2020-2024). Several samples can fall in one field
  (900 m spacing limits this). Points within ~50 m of the county line are excluded by the inside-county block rule.
- County assignment is point-in-polygon on the 1:500k boundaries.
- CDL confidence layers were not used.

## Re-run (from `apps/drought-bill/`)
```
PY=/home/user/venv-db/bin/python
$PY pipeline/cdl_pc_fetch.py --threads 4    # 2008-2021, 2,828 tile reads (~9 min); per-tile cache in data/raw/cdl/pc_tiles/
$PY pipeline/cdl_nass_fetch.py --threads 4  # 2022-2024, ~1.1-1.5 GB per year (~1-1.5 min each); deletes big files
$PY pipeline/cdl_metrics.py                 # ~3.5 min, a few GB of RAM
$PY pipeline/cdl_focus.py                   # ~10 s
```
Both fetch scripts skip cached work (per tile-year `.npz`, per-year `lattice_<year>.npy`, focus clips). SAS URLs are
re-signed on every attempt. Cache: `data/raw/cdl/` (~710 MB: 17 lattice arrays of 36 MB each, 118 MB of tile caches,
focus clips). Total wall time of the first run: ~20 min (PC and NASS fetches ran concurrently with 4 threads each).
