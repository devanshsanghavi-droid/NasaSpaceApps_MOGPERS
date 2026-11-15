# Claims register

Every number shown in the Water Clock app or in [PITCH.md](PITCH.md), with its value, source and status. Paths are relative to
`apps/water-clock/`. Values were read from `web/data/*.json` as regenerated in the final fix pass (2026-11-15; GMD/region decline
ranges, scenario pumping window, net-inflow gain range, two-route climate shift, decline-window sensitivity).

**Status key**
- **verified-computed**: computed by this project's code from real downloaded data; re-run `model/run_all.py` (or the named script) to reproduce.
- **verified-source**: checked against the text of the primary source, opened from the build environment.
- **unverified**: not checked against the primary source. "Search-corroborated" means web-search results quote or summarise the
  source and agree, but the page itself could not be opened (WebFetch to jpl.nasa.gov, k-state.edu and news sites failed: host not
  allowed in this environment). Use the recommended wording.

The app computes some numbers in the browser (`web/js/scenario.js`) from these files; those are listed with the formula.

## 1. Headline and region (app header, pitch slides 1-2, video)

| Claim | Value | Source | Status |
|---|---|---|---|
| Years of irrigation water left, typical irrigated acre, region, 30 ft threshold (p50) | 68.7, shown as "69" | `web/data/county_clocks.json` → `region.years_left["30"].p50` | verified-computed |
| Likely range (p10 to p90) | 23.7 to 100 (shown "24 to 100+") | same, `p10`, `p90` | verified-computed |
| Region years left at 15 ft / 50 ft (p50) | 84.9 / 43.8 | `region.years_left["15"/"50"]` | verified-computed |
| Share of irrigated acres with fewer than 25 years | 15.1% | `region.share_irrigated_acres_under_25y` = 0.151 | verified-computed |
| Share of irrigated acres at the 100-year cap | 30.5% | `region.share_irrigated_acres_capped` | verified-computed |
| Region saturated thickness p50 (p10, p90) | 105 ft (38, 240) | `region.sat_thick_ft` | verified-computed |
| Region decline rate | 1.34 ft/yr (0.66 to 2.02) | `region.decline_ft_yr` (fixed: earlier ranges reused one county's spread and were 2-3x too narrow) | verified-computed |
| Region p50 at 30 ft by decline window: 2001-2026 / 2011-2026 (used) / 2016-2026 | 58.8 / 68.7 / 76.8 years ("59 to 77"); acres under 25 y 19.6% / 15.1% / 12.8% | `county_clocks.json` → `sensitivity.decline_window.windows` | verified-computed |
| County p50 by window (2001 / 2011 / 2016 start): Ford, Gray, Finney | 49.6 / 62.0 / 84.0; 24.3 / 31.1 / 41.6; 41.3 / 44.8 / 54.5 | same | verified-computed |
| Reported pumping 2016-2025 vs 2011-2013 | -28.4% (2.04 vs 2.85 million AF/yr) | `sensitivity.decline_window.pumping_2016_2025_vs_2011_2013_pct` ← WIMAS `irr_af_gw` | verified-computed |
| Population of the 26 counties | 170,836 ("about 171,000") | `region.population_2025` ← Census 2025 estimates via `county_context.json` | verified-computed |
| Crop sales, 26 counties (25 with a value) | $2.51 billion (2022) | `region.crop_sales_usd_2022` ← Census of Agriculture 2022 | verified-computed |
| Total agricultural sales, 26 counties | $12.7 billion (2022; mostly livestock, not all irrigation-dependent) | `region.ag_sales_total_usd_2022` | verified-computed |
| Header stat "shortest county clocks" | Wichita 0 · Hamilton 2 · Wallace 4 | three lowest county p50 at the chosen threshold | verified-computed |
| Counties at 100+ years (30 ft) | 8 | `counties[].years_left["30"].p50` = 100 | verified-computed |
| Header NASA line (POWER, GRACE/GRACE-FO, NEX-GDDP-CMIP6) | | `web/index.html`; roles per `meta.json` | verified-computed |
| Irrigated points in the region clock | 12,907 | `region.n_fields` | verified-computed |
| Clickable irrigation wells (fields) | 13,233 | `web/data/fields.json` rows | verified-computed |
| Monitoring wells used for decline rates | 929 | `region.n_wells`; `notes/model.md` §1 | verified-computed |
| Wells used for saturated thickness | 917 | `notes/model.md` §2 | verified-computed |
| Reported groundwater irrigation pumping, mean 2016-2025 | 2,037,867 AF/yr ("about 2 million") | `region.pumping_af_yr`; `data/processed/wimas_county_year.parquet` `irr_af_gw` | verified-computed |
| WIMAS irrigated acres (groundwater), mean 2021-2025 | 1,948,177 | `region.irrigated_acres` | verified-computed |
| Census of Agriculture 2022 irrigated land, 26 counties | 1,416,152 ac ("about 1.4 million") | sum of `counties[].irrigated_acres_census_2022` | verified-computed |
| WIMAS acres are about 1.4x Census irrigated land | ratio 1.39 (2022) | `notes/pumping.md` Caveats | verified-computed |
| Irrigation share of reported irrigation + municipal water use, 2016-2025 | 98.2% (2,076,577 AF irrigation vs 37,241 AF municipal per yr) | `wimas_county_year.parquet` `irr_af`, `mun_af` (computed by docs module); industrial, stock and domestic use were not fetched, so this is not the share of all pumping | verified-computed |
| Header sentence "ranges from already below 30 ft in Wichita County to 100+ in 8 counties" | | min of county p50 (with the already-below flag) and count at the cap | verified-computed |
| Region irrigated corn share | 44.4%, 865,895 ac | `region.corn_share_irrigated`, `region.irrigated_corn_acres` | verified-computed |

## 2. Districts (community view GMD cards, README, pitch slide 3)

| Claim | Value | Source | Status |
|---|---|---|---|
| GMD1 years left p50 (p10 to p90), 30 ft | 6.7 (0 to 100+), shown "7" | `county_clocks.json` → `gmds[GMD1]` | verified-computed |
| GMD1 saturated thickness p50 / decline | 32 ft / 0.26 ft/yr (0.00 to 0.52) | same | verified-computed |
| GMD3 years left p50 (p10 to p90) | 67.9 (30.8 to 100+), shown "68" | `gmds[GMD3]` | verified-computed |
| GMD3 saturated thickness p50 / decline | 154 ft / 1.71 ft/yr (0.85 to 2.58) | same | verified-computed |
| GMD4 years left p50 (p10 to p90) | 98.4 (0 to 100+), shown "98" | `gmds[GMD4]` | verified-computed |
| GMD4 saturated thickness p50 / decline | 71 ft / 0.50 ft/yr (0.16 to 0.84) | same | verified-computed |
| GMD 15 ft p50: GMD1 / GMD3 / GMD4 | 57.8 / 80.0 / 100+ | `gmds[].years_left["15"]` | verified-computed |
| Wallace sensitivity: GMD1 / GMD4 with Wallace in GMD1 | 5.4 / 100+ years | `county_clocks.json` → `sensitivity.wallace_in_gmd1` | verified-computed |
| 90% of Wallace irrigated acres lie in the GMD1 polygon | 90% | `notes/pumping.md`, econ check `data/raw/gmd/county_gmd_check.json` (USGS ScienceBase GMD polygons) | verified-computed |

## 3. Counties (map colours, county table, county clock, slider baseline)

All values from `web/data/county_clocks.json` (`counties[]`) and `web/data/climate.json`; status verified-computed. Sorted by years left.
The app rounds years to whole numbers ("100+" at the cap). "0" = central estimate already below the threshold.

| County | GMD | Years left p50 (p10 to p90), 30 ft | 15 ft p50 | 50 ft p50 | Sat. thickness p50 (ft) | Decline ft/yr (lo to hi) | WIMAS irrigated acres | Pumping AF/yr | Monitoring wells | Data quality | 2045 shift, yr: ssp245 / ssp585 (pumping only to total weather response) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Wichita | GMD1 | 0.0 (0.0 to 100+) | 33.0 | 0.0 | 26 | 0.22 (-0.01 to 0.45) | 50,603 | 31,630 | 40 | good | 0.0 to 0.0 / 0.0 to 0.0 |
| Hamilton | GMD3 | 2.3 (0.0 to 40.4) | 10.2 | 0.0 | 34 | 1.59 (0.71 to 2.47) | 28,590 | 35,454 | 6 | thin | -0.1 to -0.4 / -0.2 to -0.6 |
| Wallace | GMD4 | 3.7 (0.0 to 80.7) | 24.3 | 0.0 | 34 | 1.29 (0.62 to 1.95) | 41,409 | 36,715 | 26 | fair | -0.2 to -0.7 / -0.4 to -1.1 |
| Greeley | GMD1 | 8.5 (0.0 to 100+) | 31.4 | 0.0 | 34 | 0.37 (0.10 to 0.64) | 17,372 | 12,487 | 14 | fair | -0.6 to -3.1 / -0.8 to -4.4 |
| Lane | GMD1 | 12.6 (0.0 to 100+) | 85.1 | 0.0 | 33 | 0.13 (-0.08 to 0.35) | 18,117 | 12,155 | 18 | fair | -0.4 to -5.9 / -0.6 to -8.1 |
| Scott | GMD1 | 29.5 (0.0 to 100+) | 66.1 | 0.0 | 44 | 0.31 (0.06 to 0.56) | 42,746 | 33,897 | 36 | good | -1.5 to -10.7 / -2.3 to -15.4 |
| Stanton | GMD3 | 30.5 (0.0 to 100+) | 42.5 | 13.8 | 69 | 1.21 (0.57 to 1.85) | 89,456 | 89,296 | 25 | fair | -2.2 to -6.8 / -3.3 to -10.1 |
| Gray | GMD3 | 31.1 (0.0 to 100+) | 42.6 | 14.1 | 69 | 1.46 (0.72 to 2.21) | 149,220 | 153,069 | 32 | fair | -2.6 to -6.7 / -3.8 to -10.0 |
| Finney | GMD3 | 44.8 (23.5 to 99.0) | 51.8 | 35.4 | 150 | 2.35 (1.22 to 3.48) | 195,442 | 234,175 | 75 | good | -2.6 to -5.7 / -3.9 to -9.3 |
| Grant | GMD3 | 54.8 (20.3 to 100+) | 65.6 | 39.3 | 117 | 1.53 (0.76 to 2.31) | 96,131 | 102,896 | 28 | fair | -4.3 to -11.0 / -5.7 to -17.1 |
| Ford | GMD3 | 62.0 (0.0 to 100+) | 95.6 | 22.4 | 66 | 0.53 (0.17 to 0.88) | 80,479 | 81,005 | 52 | good | -4.3 to -23.3 / -6.5 to -33.3 |
| Kearny | GMD3 | 68.3 (28.8 to 100+) | 75.6 | 48.4 | 144 | 1.70 (0.85 to 2.54) | 88,693 | 120,342 | 29 | fair | -3.2 to -13.1 / -5.2 to -22.2 |
| Haskell | GMD3 | 70.1 (37.8 to 100+) | 78.5 | 58.9 | 155 | 1.92 (0.97 to 2.86) | 149,527 | 147,130 | 24 | fair | -5.0 to -10.9 / -7.5 to -17.1 |
| Sheridan | GMD4 | 80.3 (0.0 to 100+) | 100+ | 24.6 | 61 | 0.37 (0.07 to 0.67) | 81,280 | 63,314 | 59 | good | -5.0 to -29.9 / -7.6 to -43.6 |
| Sherman | GMD4 | 85.0 (22.6 to 100+) | 100+ | 55.6 | 91 | 0.71 (0.30 to 1.13) | 118,379 | 110,055 | 60 | good | -5.4 to -23.1 / -8.5 to -35.2 |
| Thomas | GMD4 | 89.1 (4.3 to 100+) | 100+ | 46.7 | 74 | 0.46 (0.13 to 0.78) | 105,240 | 87,407 | 63 | good | -5.3 to -30.6 / -7.8 to -45.3 |
| Stevens | GMD3 | 91.6 (55.4 to 100+) | 98.3 | 82.5 | 247 | 2.29 (1.18 to 3.40) | 170,043 | 213,646 | 34 | fair | -5.6 to -12.7 / -8.5 to -19.9 |
| Morton | GMD3 | 94.5 (7.2 to 100+) | 100+ | 43.7 | 78 | 0.62 (0.21 to 1.03) | 43,910 | 45,758 | 33 | good | -10.6 to -39.6 / -15.1 to -54.5 |
| Seward | GMD3 | 100+ (61.0 to 100+) | 100+ | 90.6 | 213 | 1.73 (0.87 to 2.59) | 127,079 | 156,863 | 34 | good | -4.1 to -14.1 / -7.1 to -23.1 |
| Meade | GMD3 | 100+ (70.8 to 100+) | 100+ | 100+ | 225 | 1.59 (0.79 to 2.39) | 126,962 | 157,910 | 30 | good | 0.0 to -4.8 / 0.0 to -13.0 |
| Cheyenne | GMD4 | 100+ (23.6 to 100+) | 100+ | 100+ | 84 | 0.30 (0.01 to 0.59) | 48,329 | 49,741 | 59 | good | 0.0 to -11.5 / 0.0 to -31.5 |
| Rawlins | GMD4 | 100+ (31.7 to 100+) | 100+ | 100+ | 81 | 0.19 (-0.09 to 0.47) | 20,492 | 18,010 | 44 | good | 0.0 to -10.0 / 0.0 to -29.1 |
| Decatur | GMD4 | 100+ (0.0 to 100+) | 100+ | 0.0 | 39 | 0.15 (-0.12 to 0.41) | 11,405 | 9,393 | 47 | good | 0.0 to -56.7 / 0.0 to -77.8 |
| Logan | GMD4 | 100+ (0.0 to 100+) | 100+ | 40.3 | 57 | 0.10 (-0.24 to 0.44) | 8,591 | 6,491 | 11 | thin | 0.0 to -20.2 / 0.0 to -47.7 |
| Gove | GMD4 | 100+ (0.0 to 100+) | 100+ | 12.4 | 53 | 0.12 (-0.18 to 0.41) | 21,797 | 15,762 | 24 | fair | 0.0 to -34.7 / 0.0 to -60.8 |
| Graham | GMD4 | 100+ (100+ to 100+) | 100+ | 100+ | 86 | 0.01 (-0.27 to 0.30) | 16,885 | 13,266 | 26 | fair | 0.0 to 0.0 / 0.0 to 0.0 |

Other county fields shown in the county panel:

| Claim | Source | Status |
|---|---|---|
| Population, main towns (e.g. Greeley: 1,182; Tribune 709) | `county_clocks.json` `population`, `town_note` ← `data/processed/county_context.json` ← Census Vintage 2025 estimates (www2.census.gov) | verified-computed |
| Crop sales per resident (e.g. Greeley $65,313) | `crop_sales_per_resident_usd` ← Census of Agriculture 2022 (NASS bulk) / Census population | verified-computed |
| Share of local economy from irrigated agriculture | null everywhere (BEA blocked); the UI says "not available" | n/a |
| Census 2022 irrigated acres and irrigated corn acres per county | `irrigated_acres_census_2022`, `irrigated_corn_acres_census_2022` | verified-computed |
| Town public-supply wells | Not linked to the clock; `town_note` says "not verified" | n/a |

## 4. Field view (My field)

Per-field values are read from `web/data/fields.json` (columns id, lon, lat, fips, acres, crop, af_yr, sat_ft, decl, y10, y50, y90, capped);
all verified-computed by `model/clock.py`.

| Claim | Value / formula | Source | Status |
|---|---|---|---|
| Field years left p10/p50/p90 at 30 ft | `y10/y50/y90` | `fields.json` | verified-computed |
| Field years at 15 or 50 ft | `y10_15..y90_50`: the same Monte Carlo at 15 and 50 ft (e.g. well 196: 100+ at 30 ft, 28 at 50 ft); "already below" if sat_ft <= T | `fields.json`; `web/js/scenario.js` `fieldYears` | verified-computed |
| Field acres, crop, AF/yr | WIMAS 2021-2025 means; crop = most frequent single WIMAS crop, else CDL 250 m mode | `fields.json`; `notes/model.md` §2 | verified-computed |
| Years gained for a strategy at a field | Y / (1 + share x p) - Y at Y = field p50; central: capped share (`pumping_share`) and central p; low: smallest cut; high: uncapped share (`pumping_share_raw`) and largest cut | `web/js/scenario.js` `yearsGained`; `strategies.json`, `scenario.json` | verified-computed (assumes all irrigated land around the field, every crop, makes the same change; the UI says so and says the county slider moves only corn) |
| Example: Finney well 22769 (45 years) | sorghum +11 (+4 to +23); limited irrigation +11 (+3 to +19); dryland +55 (clock 100+); cotton +23 (+14 to +52) | app, `#farmer/field/22769` region of Finney | verified-computed |
| "Best fit" badge | highest priority-weighted score among plans keeping at least (1 - priority) of S0 income; none when no plan has a gain | `web/js/farmer.js` `scoreStrategies` | method |
| 2045 line on the field and county clocks | county `clock_shift_years_combined` (SSP2-4.5): pumping only to total response, e.g. Finney -2.6 to -5.7 | `climate.json` | verified-computed |
| Fields left null (no aquifer in USGS 2009 map) | 326 of 13,233 | `notes/model.md` §2 | verified-computed |

## 5. Strategy cards (`web/data/strategies.json`)

| Claim | Value | Source | Status |
|---|---|---|---|
| S0 continuous irrigated corn: water | 14.8 in/acre (12.6 to 18.9) | `strategies[S0].water_in_ac` ← WIMAS single-crop points 2011-2025 | verified-computed |
| S0 income over operating cost | $366/acre (265 to 742) | `strategies[S0].income_usd_ac` ← NASS yields x KS price - ERS Prairie Gateway cost, 2016-2025 | verified-computed |
| S1 corn-wheat-sorghum, limited irrigation: water / pumping change / income | 10.0 in (9.2 to 11.5) / -32% (-40 to -9) / $236 (201 to 367) | `strategies[S1]` | verified-computed |
| S2 dryland wheat-sorghum-fallow: water / pumping / income | 0 / -100% / $53 (30 to 96) | `strategies[S2]` | verified-computed |
| S3 irrigated sorghum: water / pumping / income | 10.2 in (8.6 to 12.0) / -31% (-45 to -14) / $297 (223 to 533) | `strategies[S3]` | verified-computed |
| S4 irrigated cotton (7 southern counties): water / pumping / income | 9.9 in (5.8 to 16.0) / -40% (-53 to -29) / $253 (189 to 531) | `strategies[S4]` | verified-computed |
| Region crop water medians: corn 14.6, sorghum 10.3, wheat 8.9, cotton 10.1, soybeans 13.8, alfalfa 19.1 in/acre | | `strategies.json` → `crop_water_in_ac` | verified-computed |
| Sorghum uses about 29% less water than corn (10.3 vs 14.6) | 29% | same | verified-computed |
| MODIS: sorghum fields about 1.1 in/yr less ET than corn; corn - wheat 2.3 in | 1.07 / 2.27 in | `strategies.json` → `modis_check_in` ← MOD16A3GF pure-crop cells 2008-2024 | verified-computed (relative check only; MODIS underestimates irrigated ET) |
| Irrigated corn yield CV about 12%, dryland corn about 47%, dryland wheat about 32% | | strategy evidence ← NASS county yields 2000-2018 | verified-computed |
| Dryland wheat after fallow about 97% of all-practice wheat yield; dryland sorghum about 92% | | strategy evidence ← NASS 2000-2018 | verified-computed |
| Cotton reported in 7 counties in at least 5 years since 2011; 4,348 acres average 2021-2025 | | strategy evidence ← WIMAS | verified-computed |
| ERS sorghum costs: about 4% of surveyed acres irrigated | 4% | strategy gaps ← `data/processed/costs.json` (ERS 2025) | verified-computed |
| Sheridan County irrigation 78,306 AF/yr (2008-2012) vs 67,562 AF/yr (2013-2017), -14%; Thomas County -4% | | `strategies.json` → `sheridan_check` ← WIMAS | verified-computed (county totals include land outside the LEMA; weather differs between periods) |
| Limited-irrigation corn capped at 11 in/acre = one fifth of the 55-inch, 5-year Sheridan-6 LEMA allocation (2013-2017) | 55 in / 5 yr | strategy text (S1 why) | **unverified, search-corroborated** (KDA Order of Designation, 17 Apr 2013; KSU slides "Sheridan #6: 5 year 55\" allocation"). Card text now: "capped at 11 in/acre a year, one fifth of the 55-inch, 5-year allocation set for the Sheridan-6 LEMA (2013-2017)". |
| Deines et al. 2019 (ERL 14:044014): about 31% less water use in 2013-2017 than a modelled no-LEMA baseline, mostly by irrigating less and more efficiently, with some switching to crops such as sorghum | 31% | strategy evidence S1 (card says search-corroborated) | **unverified, search-corroborated**. An efficiency/crop-change split (72% / 19%) seen in an earlier draft could not be confirmed by search and is not used. |
| Steward et al. 2013 PNAS: 30% of Kansas High Plains aquifer groundwater pumped by 2010, another 39% projected by 2060 (69% in total) | 30% + 39% | strategy evidence (S0), card text corrected | see §10 |
| S4 cotton card: "already grown on some irrigated fields in 7 southern counties (about 4,348 reported acres a year in 2021-2025)" | | `strategies.json` S4.why ← WIMAS `acres_cotton` | verified-computed (replaces "spreading into southwest Kansas", which WIMAS does not support: region cotton acres 9,249 in 2017, 2,961 in 2025) |
| Gray County per-county incomes (pitch slide 4): S0 $360, S1 $291, S2 $81, S3 $405 /acre | | `strategies.json` → `per_county["20069"]` | verified-computed |
| Gray sorghum pumps about 38% less than corn (9.40 vs 15.16 in) | 38% | same | verified-computed |
| Counties where irrigated sorghum income is at or above corn | 9 of 26 (Gray, Sherman, Logan, Graham, Wichita, Greeley, Wallace, Hamilton, Lane) | same | verified-computed (sorghum irrigated yields after 2009 estimated from NASS ratios) |
| OpenET described as "NASA-supported", not a NASA dataset | | `meta.json` | verified-source (OpenET is a NASA-supported consortium product; wording kept cautious) |

Per-county card values (`strategies.json` → `per_county[fips][Sk].net_pumping_in_ac`, `income_usd_ac`) replace the region central
values in the field view: verified-computed. Example Finney: S0 15.21 in, $379; S1 12.26 in, $211; S2 0, $64; S3 12.27 in, $273; S4 10.11 in, $220.

## 6. Community slider and "years a rotation buys back" (pitch slide 4, video)

Formula (`scenario.json` → `formula`, `web/js/scenario.js` `countyShift`): saved_af = X x irrigated_corn_acres x (net_S0 - net_Sk)/12;
new_decline = decline - decline_from_pumping x saved_af / pumping_af_yr; years = sat_avail_ft[T] / decline (cap 100). Range = same with
decline lo/hi. Net-inflow reading = same with `decline_from_pumping_ft_yr_net_inflow` (uncapped pumping share). `pumping_af_yr` in
scenario.json is now the 2011-2025 mean (same years as the decline window; 2016-2025 kept as `pumping_af_yr_2016_2025`), so gains are
about 9% smaller than in the previous version. Values below computed by importing `web/js/scenario.js` in Node with the committed data.

| Claim | Value (central; range over decline lo/hi; net-inflow reading) | Status |
|---|---|---|
| Gray County, 100% of irrigated corn to S1 (limited-irrigation rotation) | 31.1 → 35.8 years, +4.7 (+3.1 to +9.5); net inflow +5.6; saves 22,176 AF/yr | verified-computed |
| Gray County, 100% to S3 (sorghum) | 31.1 → 36.2, +5.1 (+3.4 to +10.3); net inflow +6.1; 23,654 AF/yr | verified-computed |
| Gray County, 100% to S2 (dryland) | 31.1 → 49.3, +18.2 (+12.0 to +36.9); net inflow +23.5; 62,257 AF/yr | verified-computed |
| Gray County, 50% to S1 (slider default view) | 31.1 → 33.3, +2.2 (+1.4 to +4.4); net inflow +2.6; 11,088 AF/yr | verified-computed |
| Finney County, 100% to S1 / S2 | +3.0 (+2.0 to +5.7) / +21.4 (+14.0 to +21.4); net inflow +3.7 / +29.6 | verified-computed |
| Stanton County, 100% to S1 | 30.5 → 36.3, +5.8 (+3.8 to +12.4); net inflow +9.1 | verified-computed |
| Region, 50% of irrigated corn to S1: water saved | 172,153 AF/yr = 8.4% of reported groundwater irrigation pumping (2016-2025) | verified-computed (sum of county saved_af) |
| Region, 100% of irrigated corn to S1 / S3 / S2: water saved | 344,306 (16.9%) / 329,971 (16.2%) / 1,068,901 (52.5%) AF/yr | verified-computed |
| Zero-shift check | 0% shift reproduces every county clock at 15/30/50 ft | `scenario.json` `zero_shift_check = "passed"` | verified-computed |
| Pumping share of decline capped at 1 in 20 counties; uncapped ratio 1.03-5.1 where above 1 (Sheridan 3.6, Rawlins 5.1) | | `scenario.json` `pumping_share`, `pumping_share_raw` | verified-computed |
| Sheridan-6: a 35% pumping cut slowed the decline by about 80% (2 ft/yr to about 5 in/yr) | used in the farmer card fine print | KGS 2017 release, §10 | verified-source (80% = 1 - 5/24) |

Caveats: counties at the 100-year cap show no gain; Wichita (already below 30 ft) shows no gain at 30 ft (`median_below_threshold_note`).

## 7. GRACE, "From space" view (`web/data/grace.json`, pitch slide 5, video)

| Claim | Value | Source | Status |
|---|---|---|---|
| GRACE/GRACE-FO (GFZ RL06) storage anomaly, region, annual mean 2003 | +5.1 cm | `grace.json` `series.tws_cm` (annual mean of monthly values) ← GFZ GravIS | verified-computed |
| Same, 2026 (Jan-Aug) | -19.1 cm | same | verified-computed |
| Storage drop 2003 → Jan-Aug 2026 ("about 24 cm lower"; independent of the file's zero point; shown in the From space headline) | 24.2 cm | same | verified-computed |
| Same, 2012 / 2014 / 2019 / 2023 | -5.7 / -9.2 / +0.3 / -15.1 cm | same | verified-computed |
| Latest monthly value (2026-08) | -25.3 cm | same | verified-computed |
| GRACE-DA groundwater percentile, region, 2026-09 | 2.5 (lowest of the monthly sample); relative to the same time of year in 1948-2012 (CLSM climatology without pumping: a drought index, not a volume) | `series.gws_pct` ← nasagrace.unl.edu | verified-computed |
| GRACE-DA latest value shown (2026-11) | 8.3 | same | verified-computed |
| Correlation wells vs GFZ GRACE (annual) | r = 0.86 (year-to-year changes 0.49) | `wells_vs_grace.correlation`; `validation.json` | verified-computed |
| Correlation wells vs G3P groundwater / GRACE-DA percentile | 0.80 / 0.68 | `validation.json` → `grace_vs_wells` | verified-computed |
| Well-based storage trend 2003-2026 | -3.96 cm/yr (range -2.64 to -5.28 for Sy 0.10-0.20) | `wells_vs_grace.trend_wells_cm_yr` (the Sy_app series was removed: Sy_app is a pumping-response coefficient, not a storage coefficient) | verified-computed |
| GRACE trend 2003-2026 | -0.90 cm/yr (-0.62 to -1.17) | `wells_vs_grace.trend_grace_cm_yr` | verified-computed |
| "About 4 times smaller" (3 to 6 times over Sy 0.10-0.20) | 3.96/0.90 = 4.4 | same | verified-computed |
| 2018-2026: wells -3.26 vs GRACE -2.19 cm/yr | | `validation.json` | verified-computed |
| Reported pumping equals 4.2 cm/yr over the region | 4.23 | `wells_vs_grace.pumping_reported_cm_yr` | verified-computed |
| GFZ trend -0.89 cm/yr = about 0.43 million AF/yr over 59,444 km2 | | `notes/nasa_water.md` §1b | verified-computed |
| 89% of the region is underlain by the aquifer | | `notes/model.md` §6 | verified-computed |
| GRACE footprint "a few hundred kilometres" | | UI text (`web/js/grace.js`), `grace.json` notes, `meta.json` caveats, PITCH (fixed from "~300 km") | general description; the reason for the wells-GRACE gap is marked untested |
| UI text: "The groundwater percentile compares each week with the same time of year in a 1948-2012 reference period (0 = driest, 100 = wettest)" | | `web/js/grace.js` (fixed) | per `notes/nasa_water.md` §1a |
| Southern High Plains GRACE loss about 2.5 cm/yr (2003-2012), NASA/JPL PIA16840 | -2.5 ± 0.2 cm/yr | https://www.jpl.nasa.gov/images/pia16840-grace-measures-groundwater-changes-across-the-us/ | **unverified, search-corroborated** (search results quote the caption: "Southern High Plains Aquifer ... -2.5 ± 0.2 centimeters (-0.98 ± 0.08 inches) per year", 2003-2012, CSR RL05). Not shown in the app. If used: "NASA's GRACE showed the southern High Plains (Texas/Oklahoma panhandles, south of our region) losing about 2.5 cm of water a year in 2003-2012". Do not apply it to western Kansas: our region's GRACE trend is -0.9 cm/yr. |

## 8. Validation (Proof & data view, VALIDATION.md, pitch slide 6)

All from `web/data/validation.json`; verified-computed.

| Claim | Value |
|---|---|
| 2014 fold, 10-yr change, temporal (n = 695): model MAE / RMSE / bias | 6.13 / 9.98 / -5.10 ft |
| Same, no change / own trend / county trend MAE | 6.25 / 7.42 / 7.80 ft (no-change RMSE 9.58) |
| 2014 fold spatial (n = 145): model vs no change MAE | 6.64 vs 5.94 ft |
| 2004 fold temporal (n = 636): model vs no change MAE | 6.65 vs 12.20 ft |
| 2004 fold spatial (n = 131): model vs no change MAE | 7.60 vs 13.21 ft |
| 80% interval coverage, 10-yr change | 91%, 89%, 88%, 87%; latest level 83-93%; all 8 tests "83-93%" (pitch, README, Proof tile) |
| Observed mean 10-yr change 2014-2024 vs 2004-2014 | -4.8 vs -11.8 ft (`notes/model.md` §5) |
| Model forecast mean change, 2014 fold | -9.9 ft |
| Predicted vs observed correlation, 2014 fold | 0.69 (temporal), 0.76 (spatial) (`notes/model.md` §5) |
| Saturated thickness vs USGS 2009: cells / MAE / median diff / r | 10,534 / 17.7 ft / +3.8 ft / 0.966 |
| Pumping vs decline across 26 counties: R² / Sy_app (80%) | 0.90 / 0.204 (0.186 to 0.226) |
| Within-county year-to-year R² | 0.14 |
| Pooling effect, 2014 temporal MAE | 6.13 pooled vs 6.74 unpooled |
| Decadal variability of decline rates ("about 35%") | k_rel 0.36, floor 0.16 ft/yr (`model_settings.regime_sd`) |
| HLS irrigated vs dryland corn: accuracy / kappa (n = 299) | 0.92 / 0.83 (`data/processed/hls_irrigation_metrics.json`, `notes/nasa_land.md` §4) |
| HLS all crops pooled: accuracy / kappa (n = 742) | 0.76 / 0.51 |
| IMERG vs POWER precipitation r: region annual / Apr-Sep / county-year | 0.89 / 0.93 / 0.87; IMERG +1.15 in/yr wetter (`notes/nasa_water.md` §3) |
| Monte Carlo draws; agreement with 200k draws | 10,000; within about 1.5 years (`notes/model.md` §3) |

## 9. Climate 2045 (`web/data/climate.json`)

| Claim | Value | Status |
|---|---|---|
| Apr-Sep reference ET change, SSP2-4.5 / SSP5-8.5 (5 GCMs) | +5.9% (2.8 to 10.6) / +8.3% (6.4 to 9.3) | verified-computed (← NEX-GDDP-CMIP6 via NASA NCCS THREDDS) |
| Apr-Sep rain change | +0.44 in (-1.22 to +1.60) / -0.63 in (-2.57 to +0.30) | verified-computed |
| Extra irrigation for corn | +1.21 in/acre (0.49 to 2.25) / +1.80 (1.37 to 2.11) | verified-computed |
| Region clock shift, pumping-only route (extra irrigation demand; recharge unchanged) | -4.9 years (-8.8 to -2.0) / -7.2 (-8.6 to -5.7) | verified-computed (was -5.4 / -8.0 before the scenario pumping window changed) |
| Region clock shift, total-response route (fitted response of winter water levels to Apr-Sep weather: -0.133 ft per in ET0, +0.076 ft per in rain; includes recharge) | -17.3 years (-28.7 to -6.2) / -26.0 (-30.2 to -22.3) | verified-computed; pitch/README "about 5 to 17" and "7 to 26" years |
| Largest county shift, pumping only: Morton | -10.6 / -15.1 years | verified-computed |
| Largest county shift, total response: Decatur (capped clock with a slow decline) | -56.7 / -77.8 years | verified-computed (an upper estimate; the regional weather coefficient is applied everywhere) |
| Timing | the 2035-2055 change is applied from today over the whole horizon (overstates near-term effects) | method |
| JJA Tmax change | +3.5 F / +4.7 F | verified-computed (`notes/nasa_water.md` §4) |
| Irrigation response: 0.36 in more water per inch of Apr-Sep ET0; -0.095 per inch of rain | | verified-computed (WIMAS panel 1990-2025, `notes/model.md` §7) |

## 10. Outside facts (pitch, strategy cards, concept spec)

| Claim | Where used | Source | Status and recommended wording |
|---|---|---|---|
| 30 ft saturated thickness as the usable minimum for large-volume irrigation | UI ("usually 30 ft, the approximate minimum Kansas agencies use for large-volume irrigation wells", fixed), README, pitch | KGS High Plains Atlas, "Estimated Usable Lifetime", https://www.kgs.ku.edu/HighPlains/atlas/ateul.htm (opened with curl: "30' has been identified by KWO, KDA-DWR, and KGS as a conservatively low ..." and "the 30' example used here is only an approximation") | **verified-source** for "KGS, KWO and KDA-DWR use 30 ft as an approximate minimum for large-volume pumping". The UI phrase "most wells can no longer supply a center pivot" goes further than the source. Recommended UI wording: "usually 30 ft, the approximate minimum Kansas agencies use for large-volume irrigation wells". |
| Sheridan-6 LEMA: goal 20%, achieved 35% reduction over four years; decline from about 2 ft/yr to about 5 in/yr "without affecting the bottom line of producers" | Pitch slide 4 | KGS news release, 31 Jul 2017, https://www.kgs.ku.edu/General/News/2017/stabilize.html (opened with curl; quote from J. Butler, KGS) | **verified-source**. Wording: "Farmers in the Sheridan-6 LEMA aimed to cut pumping 20% and cut it 35% over four years; the KGS reported the decline slowed from about 2 ft to about 5 inches a year without hurting their bottom line." |
| Steward et al. 2013 PNAS: about 69% of the groundwater stored in the Kansas High Plains aquifer depleted within 50 years if trends continue | Strategy card S0 evidence; concept spec | doi:10.1073/pnas.1220351110; K-State release https://www.k-state.edu/news/newsreleases/aug13/groundwater82613.html | **unverified, search-corroborated**. Search results: 3% used by 1960, 30% by 2010, a further 39% projected by 2060 (= 69% cumulative); reducing use now extends the aquifer's life and total production to 2110. Recommended wording: "A 2013 Kansas State study projected that, at 2010 trends, about 69% of the aquifer's original stored water in Kansas would be used by 2060 (30% was already used by 2010)." Card text fixed: "estimated that 30% ... had been pumped by 2010 and projected that another 39% would be used by 2060 at existing trends (69% in total; a model projection, not a measurement)". |
| Kansas governor: some areas have less than 25 years left | Pitch slide 2 (†) | Gov. Laura Kelly, State of the State, January 2025 | **unverified, search-corroborated**. Search results quote: "Forget making it 75 years down the road — some parts of western Kansas don't have groundwater enough to last another 25 years." Use that exact quote with "Gov. Laura Kelly, January 2025"; do not paraphrase as "less than 25 years left". Our own data say the same independently: 15% of irrigated acres have fewer than 25 years. |
| Irrigation is about 80-90% of High Plains pumping (USGS) | Concept spec only; not in app or pitch | USGS | **unverified**. Search results cite USGS Nebraska WSC: about 95% of High Plains aquifer withdrawals were for irrigation in 1990. The pitch uses our own number instead (98% of reported irrigation + municipal use, §1), which excludes industrial and stock use. |
| GRACE ~2.5 cm/yr southern High Plains (PIA16840) | Concept spec; not in app or pitch | see §7 | unverified, search-corroborated; applies to the southern High Plains, not our region |
| Specific yield prior 0.15 (range 0.10-0.20) | Model prior, GRACE comparison | McGuire, USGS SIR 2017-5040; Gutentag et al. 1984 USGS PP 1400-B (cited in `model/common.py`) | unverified (page not re-checked). Our data give Sy_app 0.204 independently. |
| Butler et al. 2016 GRL water-balance approach | Method citation | doi:10.1002/2016GL067879 | unverified citation details |
| Irrigated corn ET in SW Kansas commonly 22-26 in | `notes/nasa_land.md` only; not in app or pitch | none given | unverified; do not use |
| NASA datasets used: 8 (GRACE/GRACE-FO via GFZ GravIS + G3P, GRACE-DA, POWER, IMERG via POWER, MODIS MOD16A3GF, HLS, NEX-GDDP-CMIP6, NASADEM) | Pitch slide 7, README | `meta.json` data_sources with nasa = true and status used/partial (NASADEM added; JPL/CSR mascons listed as blocked, not counted) | verified-computed |
| "+/-22 ft" aquifer-base uncertainty at a field | README method step 2 | `model/common.py` PRIORS base_sd_ft (KGS picks vs USGS surface MAD 22.6 ft; 2009 thickness MAE 21.9 ft), `notes/model.md` §2 | verified-computed |
| "~18 ft thickness error" (pitch slide 7, "should reduce") | Pitch | USGS 2009 comparison MAE 17.7 ft (§8) | verified-computed |
| Recharge prior 0.1-1.5 in/yr | `model/common.py` | Stanton et al. 2011, USGS SIR 2011-5183; Hansen 1991, USGS WRI 87-4230 | unverified (marked verify; not re-opened); used only as a plausibility check |
