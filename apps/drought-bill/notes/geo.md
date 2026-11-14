# geo module: county shapes, NASS yields and prices, soils and irrigation

Built 2026-11-14. Region: IA 19, NE 31, KS 20, MO 29, IL 17, SD 46, MN 27 (667 counties). Key `fips` is a 5-character string.
Python: `/home/user/venv-db/bin/python`. Every script skips raw files that are already cached.

Run order:

```
pipeline/geo_counties.py      # counties.parquet, web/data/counties.geojson, web/data/states.geojson
pipeline/geo_nass.py          # nass_county_year.parquet, nass_prices.parquet  (~1 min from the cached .gz)
pipeline/geo_soils_fetch.py   # Soil Data Access SQL -> data/raw/sda/*.json (14 small queries)
pipeline/geo_static.py        # county_static.parquet  (streams the Census of Agriculture bulk files)
```

Raw caches: `data/raw/census/cb_2023_us_county_500k.zip`, `data/raw/nass/qs.crops_20261114.txt.gz` (1.13 GB),
`qs.census2022.txt.gz`, `qs.census2017.txt.gz`, the filtered rows in `data/raw/nass/rows_7state_survey_2000_2025.tsv` and
`census_7state_county.tsv`, and the SDA aggregates with their SQL in `data/raw/sda/aws_<ST>.json` and `nccpi_<ST>.json`.

---

## `data/processed/counties.parquet` (667 rows)

Source: US Census cartographic boundary file, counties 2023, 1:500k:
https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip

| column | meaning |
|---|---|
| fips | 5-character county FIPS (GEOID) |
| state_abbr, state_fips | e.g. IA, "19" |
| name, namelsad | "Plymouth", "Plymouth County" (St. Louis city MO 29510 is "St. Louis" with namelsad "St. Louis city") |
| lon, lat | interior point in WGS84 decimal degrees, 5 dp. This is the equal-area (EPSG:5070) centroid where it falls inside the polygon (665 counties), otherwise the shapely point_on_surface (2 counties). Column `interior_point_method` says which. |
| land_km2, water_km2 | Census ALAND / AWATER in km² |
| area_km2 | polygon area in EPSG:5070, km² |

Counties per state: IA 99, IL 102, KS 105, MN 87, MO 115 (including St. Louis city), NE 93, SD 66 (Oglala Lakota is 46102,
not the old Shannon 46113).

## `web/data/counties.geojson` (667 features, 0.77 MB) and `web/data/states.geojson` (7 features, 0.15 MB)

- Topology-preserving `shapely.coverage_simplify` over the whole 7-state coverage, tolerance 0.0025° (about 200-280 m), so
  neighbouring counties still share edges with no gaps. Coordinates are rounded to 4 dp. All geometries are valid
  (665 Polygon, 2 MultiPolygon).
- County properties: `{fips, name, state}`. State properties: `{state, state_fips, name}`. The states are dissolved from the
  simplified counties, so their outlines match the county edges exactly.

---

## `data/processed/nass_county_year.parquet` (40,205 rows; key fips, year, crop)

Source: USDA NASS QuickStats bulk file `qs.crops_20261114.txt.gz` (https://www.nass.usda.gov/datasets/, file updated
2026-11-14). The file is cached and then streamed line by line with `zcat`. Over 23.95 M lines, 362,116 rows were kept
(SOURCE=SURVEY, commodity CORN/SOYBEANS/WHEAT/SORGHUM, the yield, area planted, area harvested, production and price-received
statistics, the 7 states plus NATIONAL, 2000-2025). The script then uses only AGG_LEVEL=COUNTY, REFERENCE_PERIOD=YEAR and
DOMAIN=TOTAL rows for real counties (COUNTY_ANSI not blank). The NASS "OTHER (COMBINED) COUNTIES" rows and the
agricultural-district rows are left out of the output, but they are kept in the cached TSV.

| column | unit | meaning |
|---|---|---|
| crop | | `corn` (corn for grain), `soybeans`, `wheat` (all wheat), `sorghum` (sorghum for grain) |
| state_abbr, county_name, asd_code | | NASS labels; asd_code is the crop reporting district |
| yield_bu_ac | bu/harvested acre | NASS published yield (for wheat 2008+, see below) |
| planted_ac | acres | **all-purpose** planted acres (`CORN - ACRES PLANTED` and `SORGHUM - ACRES PLANTED` include silage) |
| harvested_ac | acres | harvested for grain (corn, sorghum), harvested (soybeans, wheat) |
| production_bu | bu | grain production |
| yield_irr_bu_ac, yield_nonirr_bu_ac, planted_irr_ac, planted_nonirr_ac, harvested_irr_ac, harvested_nonirr_ac, production_irr_bu, production_nonirr_bu | | irrigated and non-irrigated breakdown, only where NASS publishes it (see coverage) |
| wheat_method | | wheat rows only: `published_all_wheat` (2000-2007) or `sum_of_classes:<classes>` (2008+) |

Coverage (rows = county-years published):

| crop | rows | non-null yield | counties with any data | irrigated breakdown |
|---|---|---|---|---|
| corn | 14,244 | 14,243 | 650 | 2,402 rows, KS/NE/SD, 2000-2018 |
| soybeans | 13,505 | 13,505 | 633 | 1,384 rows, KS/NE, 2000-2018 |
| wheat | 9,133 | 9,132 | 550 | 939 rows, KS/NE(/SD), 2000-2019 |
| sorghum | 3,323 | 3,316 | 322 | 511 rows, KS/NE, 2000-2009 |

Counties with a corn yield, by year: 637 (2000), about 570-600 through 2012 (571 in 2012), 532 (2022), 498 (2023), 409 (2024),
384 (2025). Among the 650 corn counties the median has 24 of 26 years; 129 have all 26. 17 of the 667 counties never have a
published corn yield: urban counties (Ramsey MN, St. Louis city), northeast MN forest (Cook, Lake, Lake of the Woods),
Ozark MO counties (Camden, Carter, Douglas, Iron, Oregon, Ozark, Reynolds, Shannon, Taney, Washington) and Sandhills NE
(Grant, Hooker).

Caveats:
- **Suppression.** When too few farmers report, NASS leaves a county out entirely and folds it into "OTHER (COMBINED)
  COUNTIES" for its district. The county-year row is then simply missing, not flagged. It is not a "(D)" value. Missing rows
  have grown since about 2015, and 2024-2025 are the thinnest years (fewer survey responses). Plymouth County IA (19149) has
  corn yields for every year except 2020 and 2025. The combined-county and district rows are in
  `data/raw/nass/rows_7state_survey_2000_2025.tsv` if a model needs a district fallback.
- **Wheat after 2007.** NASS stopped publishing county all-wheat. For 2008+, `wheat` is the sum of the county-level classes
  (winter, spring excl. durum, durum). Yield = Σ production / Σ harvested acres, computed only when every class present has
  both values. `wheat_method` lists the classes used, and also any class that NASS published elsewhere in the state that
  year but not for this county, since that class may be suppressed (≈460 rows, MN/SD). Check of the method on 2000-2007,
  when both are published: the class sum matches published all-wheat harvested acres within 1% in 97.7% of 3,594
  county-years.
- **No 2024 county wheat** except in IL (57 counties); NASS did not publish the 2024 county small-grain estimates for the
  other states. Iowa has no county wheat after 2007, and sorghum is only published for IL KS MO NE SD.
- **Irrigated/non-irrigated breakdowns** stop after 2018 (corn, soybeans), 2019 (wheat) and 2009 (sorghum). NASS stopped
  publishing them at county level after those years. IA, IL, MN and MO never had them.
- 9 rows (NE 2001-2007, mostly corn) have planted acres but no yield, harvested acres or production.
- 2025 county values are the first county estimates for 2025 (loaded 2026-05-05). They can still be revised.

## `data/processed/nass_prices.parquet` (764 rows; key state_abbr, year, crop)

Same bulk file, `PRICE RECEIVED`, REFERENCE_PERIOD=`MARKETING YEAR`, AGG_LEVEL STATE or NATIONAL (`state_abbr`='US').

| column | meaning |
|---|---|
| price_received_usd_per_bu | marketing-year average price received, nominal $/bu |
| value_original, unit_original | NASS value and unit. Sorghum is published in **$/CWT** and converted with 56 lb/bu: $/bu = $/cwt × 0.56 |
| level | `state` or `national` |
| preliminary | True if the row was loaded before its marketing year ended (Sep 1 of year+1 for corn/soy/sorghum, Jun 1 for wheat), i.e. still a preliminary estimate |
| nass_load_time | NASS load timestamp |

Coverage: corn and soybeans, 7 states + US, 2000-2025 (208 rows each). Wheat (all wheat) 202 rows; IA ends in 2019.
Sorghum 146 rows: KS NE SD US 2000-2025, IL MO 2000-2020. Preliminary rows: the 7 state corn prices for 2025 (loaded
2026-02-26; the US 2025 corn price is final) and IA wheat 2019 (the last IA value). US MY prices, corn/soy/wheat/sorghum
($/bu): 2022 6.54/14.2/8.83/6.38, 2023 4.55/12.4/6.96/4.93, 2024 4.24/10.0/5.52/4.07, 2025 4.16/10.5/5.06/3.67.

---

## `data/processed/county_static.parquet` (667 rows, key fips, 45 columns)

### Soils (USDA NRCS SSURGO via Soil Data Access)

POST https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest (format JSON+COLUMNNAME), queried 2026-11-14. There is one
SQL per state (stored in `data/raw/sda/aws_<ST>.json`). It aggregates `muaggatt.aws0100wta` / `aws0150wta` (available water
storage 0-100 / 0-150 cm, weighted average over map unit components, **cm of water**) over `mapunit` rows weighted by
`mapunit.muacres`, per survey area (`legend.areasymbol`, areatypename = Non-MLRA Soil Survey Area).

| column | unit | meaning |
|---|---|---|
| aws0_100_mm, aws0_150_mm | **mm** of water (= cm × 10) | Σ(aws × muacres) / Σ(muacres of map units with a rating). Map units without a value (water, pits, urban) are excluded from the denominator. |
| aws_rated_frac | 0-1 | share of survey-area map-unit acres that have an AWS value (Plymouth 0.993) |
| nccpi | 0-1 | NCCPI v3 (`cointerp`, mrulename 'NCCPI - National Commodity Crop Productivity Index (Ver 3.0)', ruledepth 0). It is a component-percent-weighted mean over rated components per map unit, then muacres-weighted per survey area. |
| nccpi_rated_frac | 0-1 | share of map-unit acres with an NCCPI rating |
| sda_areasymbols | | survey areas used |
| sda_match | | `one_to_one` (655), `combined_survey_shared_value` (6), `county_split_into_parts` (3), `single_survey_other_symbol` (3) |
| sda_area_ac, sda_area_to_county_ratio | acres, ratio | survey-area acres and ratio to Census land+water area (sanity check) |

Survey areas mostly match counties one to one (areasymbol `IA149` = state code + county number → 19149). The exceptions
(`SDA_SPECIAL` in geo_static.py) were checked against `legend.areaname`:
- **MN 27071 Koochiching** → MN625 "Koochiching County Area". **MN 27137 St. Louis** → five parts MN613/615/617/619/621,
  pooled by acres.
- **MO 29510 St. Louis city** has no survey of its own. It gets MO189 (the St. Louis County survey, which covers the city).
  It shares that value with 29189.
- **SD combined surveys** (both counties get the same pooled value): SD602 Hanson + Hutchinson (46061, 46067); SD603 Brule +
  Buffalo (46015, 46017); SD606 + SD607 Custer + Pennington Counties Area, prairie + Black Hills parts (46033, 46103).
- **SD split surveys**: Meade 46093 → SD600 + SD601; Jackson 46071 → SD610 + SD611; Oglala Lakota 46102 → SD613
  (Oglala Lakota County Area).
- **Excluded**: MN627 Voyageurs National Park (spans St. Louis + Koochiching) and SD612 Badlands National Park (spans
  Jackson, Pennington, Oglala Lakota). They are not assigned to any county, so St. Louis MN covers 0.94 of its area and
  Oglala Lakota 0.90.
- Cook/Lake IL and Cook/Lake MN have ratios of 0.34-0.77 only because Census water area includes Lake Michigan / Lake
  Superior.

Result: no nulls. aws0_100_mm ranges 65-302 (median 172). State means are IA 179, MN 181, IL 175, KS 161, NE 155, SD 149 and
MO 141 mm. Plymouth: 206 mm (0-100 cm), 305 mm (0-150 cm), NCCPI 0.708.
Caveat: SSURGO survey-area polygons can extend slightly beyond county lines along rivers, and the area weighting covers all
land, not just cropland.

### Irrigation and cropland (NASS Census of Agriculture)

Cheapest correct route: the census bulk files `qs.census2022.txt.gz` (295 MB) and `qs.census2017.txt.gz` (132 MB) from
https://www.nass.usda.gov/datasets/. They are streamed and filtered to county level with DOMAIN=TOTAL for the items below.
qs.crops does carry SOURCE=CENSUS rows for crop items (e.g. `CORN, GRAIN, IRRIGATED - ACRES HARVESTED`), but not the
`AG LAND, ...` totals (harvested cropland, irrigated land), so the census files are needed.

| column | meaning |
|---|---|
| harv_cropland_ac_YYYY, harv_cropland_irr_ac_YYYY | `AG LAND, CROPLAND, HARVESTED - ACRES` and `..., HARVESTED, IRRIGATED - ACRES` |
| ag_land_irr_ac_YYYY | `AG LAND, IRRIGATED - ACRES` (all irrigated land in farms, including pasture) |
| cropland_ac_YYYY | `AG LAND, CROPLAND - ACRES` |
| corn_grain_harv_ac_YYYY, corn_grain_harv_irr_ac_YYYY, soy_harv_ac_YYYY, soy_harv_irr_ac_YYYY | crop-specific census acres |
| irrigated_share_YYYY | harv_cropland_irr / harv_cropland |
| irrigated_share_proxy_YYYY | ag_land_irr / harv_cropland, capped at 1 |
| corn_irrigated_share_YYYY, soy_irrigated_share_YYYY | irrigated / total harvested for that crop |
| cropland_share_YYYY | cropland acres / Census land area (land_km2 × 247.105) |
| **irrigated_share** | headline value, first available of: 2022 ratio (446 counties) → 2017 ratio (109) → 2022 proxy (56) → 2017 proxy (17); null for 39 |
| irrigated_share_year, irrigated_share_method | which year and tier was used |
| cropland_share, cropland_share_year | 2022, else 2017 (null only for St. Louis city 29510) |
| flag_harv_cropland_irr_ac_2022 / _2017 | the census disclosure code when withheld, e.g. "(D)" |

YYYY is 2017 or 2022. "(Z)" (less than half an acre) is treated as 0 and "(D)" (withheld) as null.

Caveats:
- The proxy tier is close to the exact ratio wherever both exist (443 counties: mean difference +0.0018, max +0.044). It is
  slightly high because it includes irrigated pasture.
- The **39 counties with null irrigated_share** have every irrigation item withheld in both censuses: SD 12, IA 9, MN 6, MO 6,
  IL 5, KS 1 (St. Louis MN 27137 and St. Louis city MO 29510 are among them). Most are in states and areas with little irrigation, but no value is
  imputed. Plymouth IA (19149) is filled by the proxy: 1,789 irrigated acres / 462,792 harvested cropland acres in 2022 =
  0.4%. Its corn irrigated share is 0.33% and soy 0.43%.
- State means of irrigated_share: NE 0.41, KS 0.10, MN 0.06, MO 0.06, SD 0.05, IL 0.03, IA 0.01.
