# econ module notes

Scripts (run from `apps/water-clock/`, all re-runnable, raw downloads cached under `data/raw/`):

| Script | Does | Output |
|---|---|---|
| `pipeline/econ_nass_fetch.py [crops\|census2022]` | Streams NASS QuickStats bulk files, keeps Kansas rows only (never writes the full file) | `data/raw/nass/ks_crops_rows.tsv` (169,589 rows), `data/raw/nass/ks_census2022_rows.tsv` (78,992 rows) |
| `pipeline/econ_nass_process.py` | County/district/state yields + harvested acres, KS prices received | `nass_county.parquet`, `prices.parquet` |
| `pipeline/econ_costs.py` | ERS Commodity Costs and Returns per-acre costs | `costs.json` |
| `pipeline/econ_boundaries.py` | Census county polygons, USGS GMD polygons, county->GMD check | `counties.geojson`, `gmd.geojson`, `data/raw/gmd/county_gmd_check.json` |
| `pipeline/econ_context.py` | Census population, main towns, Census of Ag 2022 exposure | `county_context.json` |

## 1. NASS county yields and harvested acres -> `data/processed/nass_county.parquet`

Source: USDA NASS QuickStats bulk file, listed at https://www.nass.usda.gov/datasets (no trailing slash; `/datasets/` redirects to an
unresolvable origin host). File used: https://www.nass.usda.gov/sites/default/files/datasets/qs.crops_20261114.txt.gz
(1,132,713,258 bytes, Last-Modified 2026-11-14 08:13 GMT, 23,951,351 lines streamed in ~100 s). QuickStats API is blocked.

Filter: SOURCE_DESC = SURVEY, REFERENCE_PERIOD_DESC = YEAR (final annual estimates, no forecasts), DOMAIN_DESC = TOTAL, years 2000-2025.

Columns: `county_fips` (5 chars), `county_name`, `agg_level`, `asd_code`, `year`, `crop`, `practice`, `yield`, `yield_unit`
(bu/ac; cotton lb/ac), `yield_cv_pct`, `yield_raw` (NASS string, e.g. "(D)"), `nass_desc_yield`, `harvested_acres`, `acres_raw`,
`nass_desc_acres`, `source`. Key = (county_fips, year, crop, practice).

- `agg_level`: `COUNTY` (the 26 region counties, county_fips 20xxx) | `DISTRICT_OTHER` (NASS "OTHER (COMBINED) COUNTIES" of a district,
  i.e. the counties NASS suppressed that year; county_fips `20C10`/`20C40`/`20C70`) | `DISTRICT` (NASS agricultural district totals,
  `20D10` Northwest, `20D40` West Central, `20D70` Southwest) | `STATE` (`20000`). **Filter `agg_level == "COUNTY"` before summing.**
- `crop`: corn = CORN, GRAIN; sorghum = SORGHUM, GRAIN; wheat = WHEAT, WINTER (falls back to all WHEAT only if no winter row; the
  description used is in `nass_desc_*`); soybeans = SOYBEANS; cotton = COTTON, UPLAND.
- `practice`: ALL, IRRIGATED, NON-IRRIGATED; for wheat also NON-IRRIGATED-FALLOW (following summer fallow) and
  NON-IRRIGATED-CONTINUOUS (continuous crop), useful for wheat-fallow strategies.

Rows: 4,983 total (COUNTY 3,820; DISTRICT 547; DISTRICT_OTHER 344; STATE 272).

County coverage (number of the 26 counties with a published yield):

| crop / practice | 2000-2007 | 2008-2018 | 2019-2025 |
|---|---|---|---|
| corn ALL | 26 every year | 8-25 | 9-22 |
| corn IRRIGATED / NON-IRRIGATED | 12-26 | 0-15 | **none (last county value 2018)** |
| sorghum ALL | 26 | 5-25 | 5-21 |
| sorghum IRRIGATED / NON-IRRIGATED | 19-26 | 2 in 2009, then none | none |
| wheat ALL | 26 | 11-26 | 0 (2024) - 25 |
| wheat IRRIGATED / NON-IRRIGATED | 26 | 1-14 | 1 in 2019, then none |
| soybeans ALL | 16-26 | 0-13 | 1-8 |
| soybeans IRRIGATED / NON-IRRIGATED | 0-15 | 2 in 2016 only | none |
| cotton (upland) ALL | 0-3 counties | 0-2 | 0-1 |

Fallbacks: district irrigated/non-irrigated yields end in 2018 (corn), 2019 (wheat), 2016 (soybeans), 2007 (sorghum); state-level
irrigated/non-irrigated corn ends 2018, wheat 2019, sorghum 2009, soybeans 2016. State ALL-practice yields run through 2025 for all
five crops. NASS discontinued the irrigated/non-irrigated county series; for recent irrigated vs dryland yield gaps the model has to use
the 2000-2018 county/district relationship (or ratio to ALL) and say so. Example check: Finney corn 2010 irrigated 198.9 vs non-irrigated
50.1 bu/ac, ALL 173.

## 2. Kansas prices received -> `data/processed/prices.parquet`

Same bulk file; STATISTICCAT = PRICE RECEIVED, AGG_LEVEL = STATE (Kansas), REFERENCE_PERIOD = MARKETING YEAR, 2010-2025 (2025 is the
latest marketing-year estimate in the file and may be revised).
Columns: `year`, `crop`, `price`, `unit` (USD/bu; cotton USD/lb), `price_nass`, `unit_nass`, `period`, `nass_desc`, `nass_load_time`, `source`.
- corn: CORN, GRAIN $/BU; wheat: WHEAT, WINTER $/BU; soybeans: SOYBEANS $/BU; cotton: COTTON, UPLAND $/LB (2017 missing in the file).
- sorghum: NASS publishes $/CWT; converted to $/bu with the standard 56 lb/bu (price = cwt price x 0.56); original kept in `price_nass`.
80 rows. Example 2025: corn 4.00, sorghum 3.37 (6.02/cwt), wheat 4.65, soybeans 10.10 USD/bu, cotton 0.562 USD/lb.

## 3. Costs per acre -> `data/processed/costs.json`

Source: USDA ERS Commodity Costs and Returns, https://www.ers.usda.gov/data-products/commodity-costs-and-returns (files last updated
10/1/2026): https://www.ers.usda.gov/media/4962/corn.csv, https://www.ers.usda.gov/media/4964/cotton.csv,
https://www.ers.usda.gov/media/4972/sorghum.csv, https://www.ers.usda.gov/media/4976/soybeans.csv, https://www.ers.usda.gov/media/4978/wheat.csv.
Regions: Prairie Gateway (western Kansas is in it), Heartland, U.S. total; years 2016-2025 (`by_year`), `latest` = 2025.
Per region-year: operating_usd_ac, allocated_overhead_usd_ac, total_costs_usd_ac (= operating + overhead), land opportunity cost,
capital recovery, fuel/lube/electricity, purchased irrigation water, seed, fertilizer, chemicals, gross value, net values, yield and
harvest price, irrigated/dryland % of acres in the survey base, survey base year. USD per planted acre, nominal.

Prairie Gateway 2025 (USD/planted acre): corn operating 401.25 + overhead 388.03 (26% of acres irrigated in survey base);
cotton 365.18 + 266.62 (28%); sorghum 183.21 + 266.89 (4%); soybeans 258.51 + 369.03 (20%); wheat 146.75 + 209.01 (3%).

Gap: ERS does not split irrigated vs dryland costs. KSU AgManager farm management guides (www.agmanager.info), which do, are blocked
(proxy CONNECT 403). No pumping energy cost per acre-foot is derived (no citable source reachable). Note Prairie Gateway corn is ~26%
irrigated, so its per-acre cost and yield (168 bu/planted ac 2025) mix irrigated and dryland corn.

## 4. Boundaries -> `counties.geojson`, `gmd.geojson`

- Counties: https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip (cached at data/raw/census/), 26 region counties,
  simplified (tolerance 0.0005 deg, 4-decimal coordinates), 13 KB. Properties: `fips`, `name`, `gmd` (CONTRACTS.md list),
  `gmd_by_irrigated_area` (GMD holding most WIMAS irrigated acres in the county, by official polygon), `area_km2`, `gmd_area_share`
  and `gmd_irr_share` (objects: fraction of county area / of WIMAS irrigated acres inside each GMD polygon, "none" = outside any GMD).
- GMD polygons: not downloadable from KGS (www.kgs.ku.edu/Hydro/gmd.html has only links to the GMD websites; the KGS ArcGIS hub and
  services.kgs.ku.edu are proxy-blocked). Used the USGS data release on ScienceBase "Reported 2014 water withdrawn for irrigation, acres
  irrigated, and application rates in Kansas irrigation water-use analysis regions" (https://www.sciencebase.gov/catalog/item/577b8b5fe4b0ef4d2f4223a1),
  whose regions are the five Kansas GMDs plus three broader regions. KML:
  https://www.sciencebase.gov/catalog/file/get/577b8b5fe4b0ef4d2f4223a1?f=__disk__02%2F8c%2Fbe%2F028cbe7658edefebc0bd5590c8067c4768c29858
  (DWR_region "Western Kansas GMD #1", "Southwest Kansas GMD #3", "Northwest Kansas GMD #4"). `gmd.geojson`: gmd, DWR_region,
  area_km2, source; 5 KB. These are the 2014-era GMD boundaries as drawn by USGS/KDA-DWR for that report.

County -> GMD check (`data/raw/gmd/county_gmd_check.json`; WIMAS irrigation points of diversion from the pumping module's
`wimas_use.parquet`, mean reported irrigated acres 2015-2024, point-in-polygon):
- Agrees with CONTRACTS.md for 25 of 26 counties.
- **Wallace (20199) disagrees:** 90% of its WIMAS irrigated acres fall inside the GMD1 polygon, 2.4% in GMD4 (by area 32.5% GMD1, 2.2% GMD4).
  By the contract's own rule (assign to the GMD with most irrigated area) Wallace belongs to GMD1, not GMD4. `gmd` was left as in the
  contract so all modules stay consistent; `gmd_by_irrigated_area` = GMD1 flags it. The model owner should decide.
- Partly outside any GMD (share of WIMAS irrigated acres outside all GMD polygons): Decatur 86% (only 8% of its area is in GMD4),
  Hamilton 51%, Gove 40%, Graham 33%, Rawlins 25%, Logan 19%, Cheyenne 8%. These counties' county-level numbers include non-GMD
  irrigation.

## 5. County context -> `county_context.json`

- Population: https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv
  (Vintage 2025, July 1 2025 estimate, plus April 2020 estimates base). Region total 2025: 170,836 people; largest counties
  Finney 37,505, Ford 33,993, Seward 21,073; smallest Greeley 1,182.
- Main towns: https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025_20.csv, SUMLEV 157
  (incorporated place part within county), top 3 per county by 2025 population. `part_in_county_only` marks places split across
  counties (e.g. Oakley in Logan).
- Census of Agriculture 2022: https://www.nass.usda.gov/sites/default/files/datasets/qs.census2022.txt.gz (309 MB gz, streamed, KS rows
  of the region counties + state kept). Per county: irrigated land acres, harvested cropland (total/irrigated), cropland, farm acres and
  operations, crop/animal/total sales (USD), corn/wheat/sorghum sales, irrigated and total harvested acres for corn grain, wheat,
  sorghum grain, soybeans, irrigated alfalfa and corn silage, net cash farm income, operating expenses, federal program receipts.
  `(D)` (withheld) values are null and listed in `census_of_ag_2022_suppressed` (e.g. irrigated harvested cropland is (D) in Cheyenne,
  Decatur, Greeley, Hamilton, Lane, Logan; Lane crop sales (D)).
- Derived (simple quotients): irrigated share of harvested cropland, irrigated share of corn grain acres, corn share of irrigated
  harvested cropland, crop and total ag sales per resident.
- `share_of_economy_from_irrigated_ag` = null for every county: no published figure reachable (BEA county earnings, apps.bea.gov,
  proxy CONNECT 403).

## Failures / blockers (also in BLOCKERS.md)
- apps.bea.gov / www.bea.gov: `curl: (56) CONNECT tunnel failed, response 403`.
- www.agmanager.info (KSU budgets): same 403.
- kgs-gis-data-and-maps-ku.hub.arcgis.com, services.kgs.ku.edu (KGS GMD layer): same 403.
- quickstats.nass.usda.gov: blocked (already in BLOCKERS.md); bulk files used instead.

## Caveats
- Irrigated vs non-irrigated county yields are not published after 2018 (corn) / 2019 (wheat) / 2009 (sorghum); any recent irrigated
  income estimate has to extrapolate the earlier irrigated/dryland ratio or use district/state data and must say so.
- Prices are state marketing-year averages (nominal); costs are ERS regional averages (nominal, all practices combined).
- County ALL-practice yields have many suppressed years after 2008 (see coverage table); use DISTRICT_OTHER/DISTRICT rows to fill.
- `nass_county` mixes non-county rows into `county_fips` (`20000` state, `20D10`/`20D40`/`20D70` districts, `20C40`-style
  "other counties" codes); e.g. state wheat harvested_acres is about 10,000,000. Always filter `agg_level == "COUNTY"` before joining
  on county or summing.
- One county yield is exactly 0 (Gray 2003, soybeans NON-IRRIGATED, NASS raw value "0"). It is faithful to the source; exclude
  `yield == 0` from yield-distribution ranges or treat it explicitly as a crop failure.
- Corn ALL-practice county yields exist for only 9-22 of the 26 counties per year after 2018; recent income estimates lean on
  district/state fallbacks.
- GMD encoding: all processed files now use the string form "GMD1"/"GMD3"/"GMD4" (wells_meta, wimas_* were switched from integers in
  the data fix pass). Wallace stays "GMD4" (contract list) everywhere; see section 4.
