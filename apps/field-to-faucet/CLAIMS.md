# Field to Faucet: claims register

This file lists every number shown in the web app (`web/js/*.js`, `web/index.html`, the text fields of `web/data/*.json`)
or in `PITCH.md`. Each entry gives the value or range, where it appears, its source and how well it is verified.
Values were checked against the files on 2026-11-15. USGS data run through 2026-11-13. Scenario numbers come from
`web/data/scenarios.json` (generated 2026-11-15T00:42Z).

**Verification status**
- **primary**: read on the original source page or dataset. The quote and check date are in `docs/facts.json`
  (`quote`, `checked_at`).
- **secondary**: from a source that quotes the original, which we could not open (blocked host or no access).
- **derived**: our arithmetic on primary numbers (for example, ban days counted from primary start and end dates), or
  our count on primary measured data (USGS, NASA).
- **model**: an output of our models (counterfactual or estimate). `VALIDATION.md` says how far each is tested.
- **unverified**: not confirmed by any source we opened. The exporter drops unverified facts (EQIP 328 rate). A few
  wording-level claims are marked unverified below until a quote is stored.

**Where shown (abbreviations)**
| abbreviation | place |
|---|---|
| Hero | city view headline, impact slider and the four impact tiles |
| KPI | city view "record, with sources" strip and lede |
| Replay | 2025/2026 replay |
| River | river chart |
| Map | hotspot map and list |
| Outlook | 14-day outlook |
| NASA | the "What NASA sees" strip |
| Farmer | field panel, leak calendar and NDVI chart |
| Cards | comparison table and strategy cards |
| Method | the "How we know" view |
| Meta | caveats in `meta.json` |
| P1-P7 | pitch slides |
| SN | speaker note |
| V | 30-second video |

Most source URLs below are stored with the value in `docs/facts.json`, which is exported to `web/data/facts.json` so
that the app can link each tile to its source. The fact id is shown in backticks.

---

## 1. Water utility, bans and drinking-water standard

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| People served by Central Iowa Water Works (CIWW) | more than 600,000 ("600k+" on the tile) | Hero, KPI, P1, P2, V | https://ciww.gov/central-iowa-water-works-returns-to-everyday-water-stewardship-as-nitrate-removal-facility-concludes-193-days-of-operation/ (`water_people_served`) | primary | |
| First-ever lawn-watering ban | began 12 Jun 2025 | P1 | IPR 2025-06-20: https://www.iowapublicradio.org/ipr-news/2025-06-20/des-moines-lawn-watering-ban-central-iowa; `ban_2025_start` claim text ("CIWW's first-ever lawn-watering ban") | primary (via `ban_2025_start`) | the IPR host is blocked from this build session, so the IPR page was not re-opened on 2026-11-15 |
| Second ban, 2026 | began 8 Jun 2026, "about 600,000 people" | P1, V ("twice in two summers") | https://ciww.gov/central-iowa-water-works-issues-stage-3-water-warning/ (`ban_2026_start`) | primary | |
| 2025 lawn-watering ban | **up to 56 days** (12 Jun-7 Aug 2025; local governments and schools last); **homes 40 days** (to 22 Jul); businesses 48 days (to 30 Jul) | Hero, KPI ("up to 56 (homes: 40)"), P2 title and bullets | `ban_2025_days`, from primary dates `ban_2025_start`, `ban_2025_residential_eased` (https://ciww.gov/lawn-watering-to-resume-july-22-following-a-phased-approach/) and `ban_2025_end` (https://www.kcci.com/article/central-iowa-water-works-lawn-watering-ban-ends-des-moines/65625319) | derived | never "56-day ban for 600,000" without "(homes: 40)" |
| 2026 lawn-watering ban | **23 days for homes** (8 Jun-1 Jul); **42 days for businesses and governments** (8 Jun-20 Jul) | Hero, KPI (2026 replay), P2 | `ban_2026_days`, from `ban_2026_start`, `ban_2026_residential_eased` (https://ciww.gov/central-iowa-water-works-eases-restrictions-through-phased-approach-to-stage-ii/) and `ban_2026_end` | derived | the app hero and KPI now give both figures (see Resolved) |
| 2025 nitrate-removal plant run | 112 days (10-18 Apr and 28 Apr-8 Aug 2025) | Hero, KPI, P2 | https://www.kcci.com/article/central-iowa-water-works-lifts-lawn-watering-restrictions-water-quality-nitrates/65789527 (`plant_days_2025`) | primary | |
| 2025 cost of removing nitrate | $2.2M ($1.6M operations and maintenance + $0.6M capital) | KPI, P2 | https://ciww.gov/what-is-the-nitrate-removal-facility/ (`plant_cost_2025_usd`, `plant_om_cost_2025_usd`) | primary | P2 says "incl. capital" |
| 2026 plant run (record length) | 193 days, Jan-Jul (6 Jan-2 Mar and 9 Mar-23 Jul 2026) | Hero ("a record 193 days (Jan-Jul)"), KPI, P2 | CIWW URL in row 1 (`plant_days_2026`) | primary | not continuous: never "193 straight days"; a record for length of run, not concentration |
| Previous record run | 177 days, 2015 | KPI (2026 "previous most"), P2 SN | https://www.kcci.com/article/central-iowa-water-works-nitrate-removal-facility-turns-off-running-for-112-days-so-far-this-year/65670201 (`plant_days_record_prior`) | primary | |
| Q1-2026 plant O&M cost | about $660,000 | P2 SN, Replay cost note, cost sensitivity | https://ciww.gov/what-is-the-nitrate-removal-facility/ (`plant_om_cost_2026_q1_usd`) | primary | |
| Q1-2026 run days | 79 (6 Jan-2 Mar = 56, 9-31 Mar = 23) | cost sensitivity | from the `plant_days_2026` dates | derived | |
| Q1-2026 O&M per run day | about $8.4k ($660k / 79 = $8,354) | Hero cost tile ("~$134k at the Q1-2026 rate"), Replay, P5 | `scenarios.json → thresholds.cost_per_plant_day_q1_2026`; fact `plant_cost_per_day_2026_q1_usd` (being added in parallel) | derived | winter, partial operation |
| Plant cost per operating day | about $14k-16k (2025 O&M $1.6M / 112 days = $14,286; "about $16,000 a day" at full capacity) | Hero footnote ("~$14k-$16k a day"), Replay, P5 | low: derived from `plant_om_cost_2025_usd` and `plant_days_2025`; high: `plant_cost_per_day_usd` (primary) | derived / primary | round to "~$14k" in prose. The $4k `range.lo` in facts.json has no quote and is unused |
| 2026 removal cost (2026 replay year) | estimate 193 days × ~$8.4k-16k/day ≈ $1.6M-3.1M, operating only | KPI (2026 replay) | arithmetic in `web/js/city.js` | derived | no full-year 2026 cost has been published; capital costs come in early 2027 (`plant_om_cost_2026_q1_usd` quote) |
| EPA drinking-water limit for nitrate (MCL) | 10 mg/L as N | everywhere (charts, KPI, footer, P2) | EPA: https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations; quoted by IPR (`mcl_mgL`, https://www.iowapublicradio.org/ipr-news/2025-06-25/nitrate-levels-central-iowa-water-des-moines) | primary (IPR quote) | the EPA host is blocked from this session. "As N" follows USGS 99133 units |
| 2025 ban-lift rule | at least one source ≤ 10 mg/L | Method (ban proxy) | https://ciww.gov/stage-iii-daily-updates/ (`ban_lift_rule`) | primary | the threshold of the ban proxy |
| Lawn watering share of summer demand | up to 40% | P2 SN, scenario caveat | https://ciww.gov/why-is-ciww-implementing-a-lawn-watering-ban/ (`lawn_watering_share_pct`) | primary | |
| Stage III trigger | demand above 90% of treatment capacity | scenario caveat | IPR 2026-06-09 (`stage3_trigger_demand_pct`) | primary | |
| Plant size vs demand | 10 million gallons/day vs 70-80 MGD normal demand | P2 SN | CIWW FAQ (`plant_capacity_mgd`), IPR (`nrf_vs_demand`) | primary | |
| Plant expansion capital | about $40M estimated; $25M from the state | Replay cost note, P5 SN, P7 SN | https://www.kcci.com/article/kcci-investigates-12-billion-in-central-iowa-water-works-projects-coming/73659187 (`capital_nrf_expansion_cost_usd`, `capital_state_grant_usd`) | primary | not avoided by any scenario |

## 2. Where the nitrate comes from, and prior art

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Share of Iowa stream N from nonpoint sources | 92% (INRS Table 1: 93%), **statewide** | Hero source line, P1 | https://www.nutrientstrategy.iastate.edu/sites/default/files/documents/1%202025%20INRS%20Executive%20Summary%20and%20Section%201_Policy%20-%20FINAL%20February%204%202025.pdf (`inrs_nonpoint_share_pct`) | primary | say "mostly farmland" or "nonpoint (mostly agricultural)", never "caused by farms" |
| Farm share for the Raccoon and Des Moines basins | about 80% (Iowa PBS summary: over 70%) | P1 | Polk County study via KCCI/Yahoo: https://www.yahoo.com/news/polk-county-research-report-confirms-232521328.html (`ag_share_river_nitrate_pct`) | secondary | the report itself was not opened |
| Row-crop share of river nitrate (scenario prior s) | 0.76-0.89 (central 0.83) | Replay method, README | INRS nonpoint 92% × CDL row-crop share (`model/out/basin_index_check.json`) | derived | |
| Existing NASA-funded nitrate forecast | University of Iowa project; "NASA is funding the project for three years" | PITCH rules, P7 | https://www.iowapublicradio.org/environment/2026-07-28/nasa-nitrate-water-quality-university-of-iowa (`nasa_nfews_prior_art`) | primary | never call ours the "first nitrate forecast" |

## 3. River measurements (our analysis of USGS data)

These are USGS NWIS daily values: parameter 99133 (nitrate + nitrite, mg/L as N) and 00060 (discharge), at sites
05484500 (Raccoon River at Van Meter, upstream of the Raccoon intake) and 05482000 (Des Moines River at 2nd Ave).
`pipeline/p02_nwis.py` fetches them into `data/processed/nwis_daily.parquet`. Day counts are on days with a
measurement.

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Raccoon days above 10 mg/L, 2025 | **115 of 356** measured days (first 26 Mar; still above 10 on 31 Dec) | KPI, Replay, P2, P5, P6 | https://waterdata.usgs.gov/monitoring-location/05484500/; `scenarios.json → by_year.2025.observed` | derived (USGS-approved data) | say "at Van Meter, upstream of the intake", not "at the intake" |
| "about 1 day in 3" | 115 / 356 | KPI lede, P2 | same; `naturalFreq()` in `util.js` | derived | |
| Des Moines River days above 10 mg/L, 2025 | 105 of 287 measured days (9 Apr-6 Aug) | Replay, P6 SN | https://waterdata.usgs.gov/monitoring-location/05482000/ | derived | no data Jan-Feb 2025, so this is a lower bound |
| Raccoon / Des Moines days above 10, 2026 (to 13 Nov) | 176 of 298 / 158 of 314 | KPI and Replay (2026) | USGS; `by_year.2026.observed` | derived | values from 2 Jun 2026 are provisional |
| CIWW count, 2026 to 8 Jun | Raccoon 136 days, Des Moines 117 days above 10 | not shown | https://ciww.gov/why-is-ciww-implementing-a-lawn-watering-ban/ (`raccoon_days_over10_2026_jun8`) | primary | for cross-checking only |
| 2025 peak daily mean | Raccoon 18.4 mg/L (7 Jun); Des Moines 17.0 mg/L (12 Jun) | River, VALIDATION | `model/out/metrics.json → crisis_2025` | derived | IPR gives 20.55 / 17.15 (different averaging). Do not claim a record concentration |
| 2026 Raccoon peak daily mean | 18.6 mg/L (28 May 2026) | River | USGS dv (`raccoon_2026_peak_mgL`) | primary (provisional) | |
| Combined nitrate load at the two gauges, 2025 | 55,300 t N (Raccoon 18,600; Des Moines 36,600) | Replay (baseline) | `by_year.2025.observed.load_tN`; `model/m07_scenarios.py` | derived | gap-fill error ≤ 2.5% of annual load in most years |
| River load per row-crop acre reaching Van Meter | about 17 lb N/acre/yr (2016-2025 mean 16.5; 1.2 in 2021 to 34.4 in 2016) | Cards (S0 evidence) | `basin_index_check.json → calibration` | derived | load delivered to the gauge, after in-stream losses |
| Last measured value at outlook issue | Raccoon 11.6, Des Moines 11.1 mg/L (13 Nov 2026) | Outlook | `web/data/outlook.json → last_obs` | primary (provisional) | |
| Days above 10 in the chart window | computed live, e.g. 365 of 1,371 measured days in "All years" (Raccoon) | River note | `river_series.json` | derived | |
| Gauge drainage areas | 3,441 sq mi (Van Meter); 6,245 sq mi (2nd Ave) | README | https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=05484500,05482000&siteOutput=expanded&siteStatus=all | primary | |
| Watershed area modelled | about 25,000 km² (Raccoon 9,004 + Des Moines 16,225 km²; 290 HUC-12s) | P3 SN, Map, README | USGS WBD via `pipeline/p01_wbd.py` | derived | the Des Moines basin extends into Minnesota |
| Row crops share of the basins | about 75-78% of land (10-year means: Raccoon 75.6%, Des Moines 77.7%) | README | USDA CDL via `pipeline/p06_cdl_shares.py` | derived | |
| 2020-2023 drought | 2020-2023 were dry years (low POWER root-zone wetness and runoff; low nitrate in 2021); wetting resumed in 2024 | Method, River "honest limit" line ("2020-23 drought"), Meta, P6 SN, README | `notes/hydro.md` (POWER GWETROOT and USGS runoff by year); context: U.S. Drought Monitor https://droughtmonitor.unl.edu/ (not opened) | derived | the legacy-N explanation that uses it is a hypothesis |

## 4. NASA data: coverage and what it shows

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Field drill-down coverage | 1,769 forty-acre (400 m) fields in 10 HUC-12s (846 km²), HLS tile 15TUG, 2020-2026 | Farmer, NASA, P3, README | `pipeline/p10_focus_area.py`, `p12_fields.py` | derived | a "field" is a grid cell, not a surveyed field |
| "About 40 acres" | a 400 m cell = 16 ha ≈ 39.5 acres | Farmer, Cards | grid definition | derived | |
| HLS living-cover threshold | NDVI ≥ 0.30 (cell median); 0.25 and 0.35 tested | Farmer NDVI chart ("living cover above 0.30"), Cards (S1 gaps), P3 | `notes/fields.md` §living cover; `pipeline/p12_fields.py` | derived (method choice) | 0.35 gives nearly the same answer; 0.25 flags bare residue |
| Fields bare (HLS) | 92% of Oct-May; 63% of Apr-Jun, 2020-2025 | Cards (S0, S2), P3 | `web/data/strategies.json` (from `hls_field_ts`, `field_month`) | derived | |
| Winter living cover seen by HLS | 2.5% of field-winters 2021-2026; 9% of fields at least once; **0.8-4.2% per year ("~1-4%")** | Hero footnote, Cards (S0, S1), P3 | `scenarios.json → hls_winter_cover_pct` (by year: 3.3, 1.2, 0.8, 4.0, 1.3, 4.2); `notes/fields.md` | derived | a lower bound: thin or late rye is missed. Statewide adoption is about 17% |
| MODIS record | 250 m, 8-day cadence (Terra + Aqua 16-day composites) from 2011-07 (v2) and 2015-07 (v1); data to 24 Oct 2026 | NASA, Map caption, P3 | `pipeline/p09_modis_cover.py`, `model/m06_history.py`; `meta.json → data_through` | derived | Jul-Nov 2025 is filled from HLS |
| Data-through dates | USGS 13 Nov, POWER 11 Nov, MODIS 24 Oct, HLS 29 Oct 2026; CDL 2025 | NASA strip, README | `meta.json → data_through` | derived | |
| NASA POWER resolution | about 50 km; smooths storm peaks | Meta, README | POWER documentation | derived | |
| IMERG check of POWER | 38 storm days, 2016-2021 (76 basin-days): r 0.62, volume ratio 1.01, slope 0.48 | NASA ("validated storm days, 2016-21"), P3, VALIDATION | `data/processed/imerg_vs_power.json`; `pipeline/p14_imerg.py` | derived | the sample was chosen on POWER-wet days |
| IMERG after May 2021 not available | Planetary Computer `gpm-imerg-hhr` ends 2021-05-31; Earthdata blocked | Meta, README, P3 SN, P7 | `BLOCKERS.md` §3; CMR check in `pipeline/p15_earthdata_check.py` | derived | V07 exists in CMR (Late to 2026-11-13) |
| HLS vs MODIS | deseasonalized r 0.63; HUC-12 ranking r 0.94 | VALIDATION | `data/processed/hls_vs_modis.json` | derived | |
| Big-storm day | day with ≥ 25 mm rain (NASA POWER) | Farmer calendar, Cards (S1) | `web/js/farmer.js`; `strategies.json` | derived (definition) | |
| Big-storm days in Apr-Jun | 34% of the year's on the average field | Cards (S1 why) | `strategies.json`, NASA POWER | derived | |
| Drainage gate | opens as POWER root-zone wetness rises from 0.45 to 0.55; monthly r 0.91 vs measured runoff | README, VALIDATION | `model/m05_fields.py` | model | |

## 5. Model results

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| v1 out-of-time skill (test 2023-25) | NSE 0.62 Raccoon, 0.56 Des Moines; climatology 0.30 / 0.27 | Method, River line ("test NSE ~0.6"), Meta, P6 | `model/out/metrics.json → sites.<site>.splits.test` | model | split fixed before fitting |
| "62% / 56% of day-to-day changes" | plain-language NSE | Method, P6 | same | model | |
| Two-reservoir model NSE (test) | 0.38 Raccoon, 0.54 Des Moines | Method | same | model | |
| 7-day persistence NSE (test) | 0.77 Raccoon, 0.90 Des Moines | Method, P6 SN | same | model | uses last week's measurement |
| v1 80% band coverage (test) | 66% Raccoon, 64% Des Moines (target 80%) | Method | same | model | |
| 2025 miss, v1 | 6 modelled vs 115 measured days above 10 (Raccoon); 10 vs 105 (Des Moines); upper bound above 10 on 121 days | Method, P6 | `metrics.json → sites.<site>.crisis_2025.gbm` | model | |
| Year-level offset 2025 | measured ≈ 1.7× (Raccoon) and 2.1× (Des Moines) what the drivers explain; 2026 1.5× / 1.8× | Method, River line, Meta ("about twice"), P6 | `web/data/validation.json → level_ratio_obs_over_model` (1.68, 2.07) | model | cause unresolved; legacy N is a hypothesis |
| v2 (post-hoc) 2025 | 83 of 115 days (Raccoon); 10 of 105 (Des Moines) | Method, P6 | `metrics.json → v2.sites.<site>.crisis_2025` | model | built after seeing the miss; kept off the headline |
| v2 test NSE (post-hoc) | 0.78 Raccoon, 0.59 Des Moines | Method, VALIDATION | `metrics.json → v2` | model | |
| Blind 2013 check (pre-registered) | measured 92 days above 10; v2 81 (NSE 0.85); v1 features 80 | Method, P6 | `metrics.json → v2.sites.05484500.blind_2013` | model | most of the gain comes from the longer record |
| Strict check 2012-19 → 2020-25 | ln-RMSE 0.75 (v2) vs 0.99 (v1 features), Raccoon; 1.20 vs 1.25 Des Moines | VALIDATION | `metrics.json → v2.sites.<site>.strict_check` | model | |
| 14-day outlook vs "no change" (test) | squared error 20% lower at 7 days, 25% at 14 days (Raccoon); 37% / 17% (Des Moines) | Outlook, Method, P6 | `metrics.json → outlook.sites.<site>.test_2023_2025` | model | no weather forecast used |
| No probability skill at 14 days | Brier skill vs probabilistic persistence +0.03 (Raccoon), −0.04 (Des Moines); greyed below +5% | Outlook, Method, P6 | same; `outlook.json → skill` | model | |
| Outlook issued 14 Nov 2026 (Raccoon) | 11.6 → 11.3 mg/L by 27 Nov (8 in 10: 9.4-12.5); about 12-13 of 14 days above 10 (expected 12.5) | Outlook | `web/data/outlook.json`; `model/m04_outlook.py` | model | Des Moines: 9.9 (8.8-12.3), about 11 days |
| Outlook drivers (as of 11 Nov 2026) | root-zone wetness 0.63, wettest since 2016 for the date; rain last 7 days 0.2 mm (21st percentile); bare cropland 75% (10th percentile; MODIS 27 days old) | Outlook | `outlook.json → drivers` | derived | percentiles use the same ±7-day window in 2016-2025 |
| Plant proxy test | fitted to 2025: 106 proxy days vs 112 reported (F1 0.94); tested on 2026 without refit: 157 vs 193, 0 false alarms (F1 0.90) | Method, Meta, P5 SN | `scenarios.json → thresholds.calibration.plant` | model | rule: 7-day mean of the two rivers' average > 10.2 mg/L |
| Ban proxy test | 2025: 66 vs 56 (F1 0.87); 2026: 40 vs 42 (F1 0.81) | Method, Hero tooltip | `thresholds.calibration.ban` | model | indicative only |
| Top 6 Raccoon hotspots | 8.8% of basin area ("9%"), 15.1% of modelled leak ("15%") | Map list, P5 SN | `web/data/huc12.geojson`, computed in `city.js` | model | ranking not validated (no sub-basin gauges) |
| Focus-area ranks | 10 HUC-12s rank 17-105 of 105 in the Raccoon | README | `huc12.geojson` | model | |
| HUC-12 popup values | row-crop share, poorly drained share, bare + wet days, share of leak, rank | Map | `huc12.geojson` (CDL, SSURGO, MODIS, POWER) | derived / model | |
| Index vs measured annual load | r = 0.75 (n = 20); water alone 0.79-0.83; partial r of the bare term −0.39 | VALIDATION | `basin_index_check.json` | model | |
| Leak timing (average field) | 91% of modelled leak Oct-May; 54% Apr-Jun | Cards (S0, S1), P3 | `notes/fields_model.md` §3 | model | |
| Living-cover leak factor ε | 0.232 (cover fields leak 28% less) | README, VALIDATION | calibrated on 187 HLS cover field-years to the INRS 28% | model | |
| Tile multiplier | poorly drained fields about 1.35× the leak of well-drained ones; prior 1-4× (central 2.5) | README | `basin_index_check.json`; McIsaac & Hu 2004 via David et al. 2010 (`tile_delivery_mcisaac_hu`, secondary) | model / secondary | |

## 6. Field values (Farmer, Cards, P4)

All values are model estimates (status **model**), not validated at field scale. Headline = long-run mean 2016-2025;
range = single-year 10th-90th percentile ("8 in 10 years"); `meanBand()` in `web/js/util.js`.

| claim | value (range) | where shown | source | notes |
|---|---|---|---|---|
| Median field leak, focus area | 13.7 lb N/acre/yr; 8.8-20.0 across fields (5th-95th pct) | Farmer, README | `basin_index_check.json → fields`; `model/m05_fields.py` | do not quote the single-year p50 (10.8) as the headline |
| Screenshot field F00179 (near Rockwell City) | leak 13.7 ("14") lb N/acre/yr (0.2-32); wet 2016 38.8 ("39", 2.8× its average); 50th percentile of nearby fields | Farmer, P4 | `web/data/field_detail/<huc12>.json → F00179.leak` | the field shown in `web/qa/farmer-*.png` |
| F00179: N kept | S1 rye before soybean 2.1 (0-5.9; wet 2016 10.8 ≈ "11", 2.2-21); S2 4-yr rotation 3.7 (0-10.6 ≈ "0-11"); S3 prairie 10% 1.2 (0-2.8; wet 2016 3.3) | Cards, P4 table | `field_detail → F00179.strategies.<S>.lbN_kept_ac` | counted at the gauge |
| F00179: fertilizer value | S1 $1.31, S2 $2.28, S3 $0.72 per acre per year | Cards | `field_detail → strategies.<S>.fert_value_usd_ac.mean` | upper bound |
| Median of all fields: N kept | S1 1.7, S2 3.7, S3 1.2 lb/acre/yr; fertilizer value $1.02 / $2.28 / $0.72 | README | all `field_detail` files | |
| F00179 calendar text | bare 93% of the time in Mar-May; 33% of big storms; 82% of yearly loss in Mar-May; 91% Oct-May | Farmer | computed live in `farmer.js` from `field_detail → calendar` | each field shows its own values |
| Per-field facts | slope %, drainage class, crop 2025, crop sequence, cover winters seen, percentile | Farmer | `field_detail`, `fields.geojson → leak_pctile` | NASADEM, SSURGO, CDL, HLS |
| Priority score | e.g. 75/100, 60/100 | Cards | `farmer.js` (`scoreTxt`) | a ranking aid, not a measurement |

## 7. Scenario results (2025 replay unless stated)

All rows come from `web/data/scenarios.json → by_year.<year>.levels[x].avoided` (headline mixture) and
`levels[x].trials_only.avoided` (trials only). Each value is the p50 with the 10th-90th percentile of 4,000 draws,
written by `model/m07_scenarios.py` (run 2026-11-15).

- **Lever (`x_definition`):** X% of all upstream corn/soy acres add cover, beyond the ~17% already covered statewide.
  At X = 25, coverage goes from about 17% to about 42%. The cover is a cereal-rye-type living cover, Oct-May, in both
  intake basins.
- **Impact basis:** each day's **measured** nitrate is cut by a fraction. Half the draws take it from the Iowa trial
  prior. The other half take it from a river-model sensitivity whose bare-soil features add no tested skill.
- **Plant days** count only days the plant really ran (the reported 2025 and 2026 run windows).

Status for every row: **model** (counterfactual, not validated).

| claim | mixture (headline) | trials only | where shown | notes |
|---|---|---|---|---|
| Removal-plant days avoided, 25% | **16 (3-34)** | **10 (2-36)** | Hero, Replay, P5 title and bullets, V | baseline 106 (102-112) proxy days inside the real run vs 112 reported. Proxy-only count (diagnostic): 24 (5-40) |
| Operating cost avoided, 25% | **about $234k ($47k-507k)** at $14.3k-16k/day; **~$134k ($25k-284k)** at the Q1-2026 rate | $157k ($29k-534k); $84k at the Q1 rate | Hero, Replay, P5 | operating cost only, an upper estimate (avoided days are often partial-output days); capital not avoided |
| Ban days avoided, 25% | **23 (9-31)** → "~3 weeks shorter", indicative | 17 (2-28) → "~2 weeks shorter" | Hero, Replay, P5 | the ban proxy gives 68 days (66-68) in 2025 vs 56 reported; weeks = round(days / 7) |
| Raccoon days above 10 avoided, 25% | **7 (2-16)**; "about 108 days (99-113) instead of 115" | 9 (1-21) | Replay, P5 | the Raccoon sat far above 10, so few days flip |
| Des Moines River days above 10 avoided, 25% | 21 (5-36) | 13 (2-28) | Replay | the river-model path drives this site |
| Nitrogen kept out of the rivers, 25% | **6.5 million lb (2.1-9.9 million)** | 4.8 million lb (1.1-10.5 million) | Hero, Replay, P5 | measured at the gauges; retention at the field edge is larger |
| Load cut at the gauges, 25% | 2,966 t N (951-4,508) of 55,300 | 2,191 t N (487-4,769) | Replay tile, P5 | |
| River-model-only plant days, 2025, 25% | 17 (7-33) | | P5 bullet, VALIDATION §9 | `headline.check_2025_25pct.plant_days_river_model_only`; the mixture leans on this unvalidated path |
| Annual load cut, 25% | trials 4.8% (both rivers); river model 2.0% Raccoon, 8.7% Des Moines | | Replay method text | `headline.check_2025_25pct.annual_load_cut_pct_p50` |
| 10% adoption, 2025 | plant days 3 (1-10); $48k ($15k-154k); ban days 9 (1-13); Raccoon days 2 (0-4); 2.6 million lb | plant days 4 (0-10); $59k ($0-149k); ban 9 (0-13); Raccoon 2 (0-5) | Replay slider | |
| 50% adoption, 2025 | plant days 35 (9-60); $528k ($134k-918k); ban days 32 (13-44); Raccoon days 16 (5-43); 13.2 million lb | plant days 31 (4-68); $470k ($62k-1.0M); ban 28 (9-50); Raccoon 18 (2-60) | Replay slider | 50% added ≈ two-thirds of acres covered |
| 2026 replay, 25% (partial year) | Raccoon days 5 (4-22); Des Moines days 30 (11-56); plant days 14 (4-29); $209k ($64k-444k); ban days 16 (1-26); 6.3 million lb | Raccoon 12 (1-30); Des Moines 21 (7-71); plant 14 (2-37); $218k ($29k-564k); ban 12 (0-29) | Replay (2026) | 2026 plant days stop at the 23 Jul shutdown; data partly provisional |
| Plain-language slider label | "1 in 4 more upstream fields/acres" = 25% | | Hero, P5, V | 25% of ALL upstream corn/soy acres added on top of ~17% today (→ ~42%), not a 25% increase in cover |
| Simulations | 4,000 draws; "8 in 10" = 10th-90th percentile | | Hero footnote, everywhere | `method_detail.n_draws` |

## 8. Agronomy and trial priors

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Cereal rye cuts drainage nitrate concentration (INRS 2024 update) | **28% averaged over the rotation**, SD 26 (corn year 27%, **soybean year 30%**); draw 10th-90th 6-54% | Cards (S1), Replay method, Meta, scenario prior, P4 | https://www.nutrientstrategy.iastate.edu/sites/default/files/documents/INRS_2024_PracticeEffienciesNitrogen_U20240319.pdf (Table 1, p. 3: "Rye - Rotational average 28 (26)"); corn/soybean-year split in `inrs_cover_rye_pct` notes | primary | a concentration cut, not a field-load guarantee |
| Rye, older INRS table | 31%, SD 29 | Cards (S1) | INRS Feb 2025 Section 2 (`inrs_cover_rye_pct`) | primary | the Feb 2025 edition still prints the 2013 table |
| Extended rotation, 4+ years (2024 update) | 27%, SD 25 (older table 42%, SD 12); 3-year 15%, SD 34 | Cards (S2) | INRS 2024 PDF; INRS 2025 Section 2 (`inrs_ext_rotation_pct`) | primary | |
| Land retirement (CRP) | 85%, SD 9 on converted land | Cards (S3) | INRS 2025 Section 2 (`inrs_crp_pct`) | primary | S3 whole-field effect = 10% × 85% ≈ 8.5% |
| Saturated buffer / bioreactor (2024 update) | 45% / 24% of treated drainage | Cards (S3 gaps) | INRS 2024 PDF | primary | treated water only |
| USDA-ARS 14-year rye experiment near Ames | 57% lower nitrate load | Cards (S1) | https://www.ars.usda.gov/research/publications/publication/?seqNo115=333537 (`kaspar_rye_pct`) | primary | |
| Rye at other Iowa sites | 15-48% lower nitrate | Cards (S1) | https://www.sare.org/wp-content/uploads/Tom-Kaspar_Session-7.pdf (`kaspar_other_sites_pct`) | secondary | SARE host blocked |
| Rye before soybean, yield | no yield loss in 27 of 28 Midwest location-years (2019-2021) | Cards (S1), P4 | https://www.ars.usda.gov/research/publications/publication/?seqNo115=405613 (`rye_before_soybean_yield`) | primary | |
| Rye before soybean, farmer trials | no detectable effect in 20 of 29 trials; gain in 8 (~10 years) | Cards (S1) | Practical Farmers of Iowa, Gailans 2019 (`E1_soy_yield_pfi`) | secondary | |
| Long-term cover adopters, soybean yield | about 3.5% lower (satellite study, ≥ 3 years of covers) | Cards (S1) | Deines et al. 2023, https://doi.org/10.1111/gcb.16489 | secondary (abstract only) | observational |
| Average Iowa corn/soy acre N loss | about 30 lb N/acre/yr (15-50) | Cards (S0) | https://stories.cals.iastate.edu/2015/11/the-science-behind-nitrate-transport (`isu_lbN_acre_yr`) | secondary | host blocked |
| Statewide cover-crop adoption | about 17% of Iowa corn + soy acres (16.7%; 3.87M acres, 2024) | Hero, Meta, P3, P5 | https://www.iowafarmbureau.com/Article/Farmers-expanding-cover-crop-notill-acres-across-the-state (`iowa_cover_share_pct`) | secondary | IDALS confirms only "nearly 4 million" acres |
| Marsden extended-rotation trial | corn +4%, soybean +9%; synthetic N −80 to −86%; herbicide −88%; profit similar or greater | Cards (S2) | Davis et al. 2012, https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0047149; https://www.ars.usda.gov/research/publications/publication/?seqNo115=282234 | primary / full text | used manure and 2003-2011 prices |
| Diverse rotations in drought | drought-year losses cut 14-90% | Cards (S2) | Bowles et al. 2020, https://par.nsf.gov/servlets/purl/10331499 | full text | no Iowa site |
| Rye and erosion | interrill erosion about half, rill about 90% lower | Cards (S1) | Kaspar 2001 via https://store.extension.iastate.edu/Product/pm1999-pdf | secondary | |
| Cover crops and infiltration | about +35% | Cards (S1) | Basche & DeLonge 2019, https://pmc.ncbi.nlm.nih.gov/articles/PMC6752860/ | full text | |
| Cover crops and soil carbon | about +4% (grass covers) | Cards (S1) | He et al. 2025, https://doi.org/10.1038/s44264-025-00050-8 | full text | |
| Rye and N2O | lower indirect N2O; direct N2O unchanged (10-year study) | Cards (S1) | Parkin et al. 2016, https://doi.org/10.2136/sssaj2016.04.0120 | abstract | |
| Prairie strips (STRIPS) | groundwater nitrate about −72%, runoff total N about −70% (non-tiled); sediment about −95% (~20-fold); total P −77%; runoff −37%; cropped-area yield unchanged | Cards (S3) | https://news.iastate.edu/news/2017/10/03/strips10years; Schulte et al. 2017, https://www.fs.usda.gov/nrs/pubs/jrnl/2017/nrs_2017_schulte_001.pdf | secondary / full text | not comparable with tile practices |

## 9. Program and cost numbers (Cards, P4, P7)

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| NRCS EQIP 340 (cover crop) | about $74/acre (FY2026 Iowa, single species); $89/acre historically underserved | Cards, P4 ("~$74, third-party figure") | https://soilpractice.com/guides/eqip-csp-after-2025-budget-law/ (`eqip_340_usd_ac`) | secondary | NRCS booklet unreachable; cards say "confirm with your NRCS office" |
| NRCS EQIP 328 (conservation crop rotation) | rate hidden | Cards (S2: "program listed, rate not verified") | `eqip_328_usd_ac` | unverified | not shown |
| IDALS cover-crop cost-share | $30/acre first-time, $20/acre returning, up to 160 acres | Cards, P4 ("state $20-30"), P7 | https://iowaagriculture.gov/news/cover-crop-cost-share-program-2026 (`idals_costshare_usd_ac`) | primary | |
| Greater Des Moines Watershed program | $25/acre on up to 500 acres, 22 counties | Cards, P4, P7 | https://iowaagriculture.gov/news/greater-dsm-watershed-program (`gdmw_costshare_usd_ac`) | primary | stackable with the state program |
| Comparison-table cost-share range | $20-74 (S1; earlier screenshots showed $25-74) | Cards table and S1 cost box | min/max of the listed programs in `farmer.js` (state returning rate $20 to EQIP ~$74) | derived | EQIP labelled "third-party figure" |
| Crop-insurance cover-crop discount | $5/acre | Cards | https://iowaagriculture.gov/news/crop-ins-discount-prog-signup-12-25 | primary | not on acres with other cover-crop cost-share |
| Rye cost | $12-27.50 per acre per year ("$12-28"); $24-55 per planting, every other fall | Cards, P4 | drilling $9-25 (avg $19.05): https://www.extension.iastate.edu/agdm/crops/pdf/a3-10.pdf; seed $15-30 (about $25): https://www.extension.iastate.edu/agdm/crops/pdf/a1-92.pdf | primary (inputs) / derived (per year) | termination pass not included |
| Prairie-strip cost | $26-33 per treated acre per year; about 75% lower with CRP CP-43 (15-year contract), $7-8 | Cards (S3), P4 | https://strips.nrem.iastate.edu/chapter-5-economics (`strips_cost_usd_treated_ac`, `strips_crp_cost_reduction_pct`) | secondary | host does not resolve here |
| Extended-rotation cost | not quantified ("not verified") | Cards (S2), P4 | Marsden: profit similar or greater | – | not ranked as $0 |
| Nitrogen price | $0.53-0.70 per lb N (central $0.67) | Replay (not in the new copy), Cards, P4 SN | low: ISU A1-88 July 2026 budget (primary); central/high: USDA AMS Iowa anhydrous $1,096/ton, https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2863/2026-04-27/1321477/ams_2863_00161.pdf (`fert_price_usd_lbN`, secondary) | primary / secondary | |

## 10. Other numbers hard-coded in app text

| text | where | basis | status |
|---|---|---|---|
| "8 in 10" ranges | everywhere | 10th-90th percentile | definition |
| "since 2016" (outlook percentiles) | Outlook | 2016-2025 reference window | derived |
| "Typical year 2020-25" | Farmer calendar | HLS field record 2020-2025 | derived |
| "Crops 2016-2025" | Farmer | CDL | derived |
| "wet year like 2016" | Farmer, Cards | highest focus-area load year (33.4 lb/acre central) | model |
| "wet years like 2016-2019 and 2024-2025" | Cards (S0 risks) | `basin_index_check.json → lbN_ac_yr_central_by_year_focus_mean` | model |
| "Removal-plant ... fitted on 2025, tested on 2026" | Method | §5 | model |
| "the 2020-23 drought" | River line, Method, Meta | §3, 2020-2023 drought | derived (cause a hypothesis) |
| "IMERG ... 2016-21" | NASA strip, Meta | §4 | derived |
| "NDVI 0.30" | Farmer, Cards | §4 | method choice |
| "25 mm+ rain" | Farmer | §4 | definition |

---

## Open items (for the app-wording pass; the facts owner is adding entries in parallel)

- **Tap water met the standard**: removed from the pitch and app (no stored source).
- `meta.json` caveat 1 says the 2025-26 level was "likely legacy nitrate after the 2020-23 drought". `VALIDATION.md`
  treats that as a hypothesis, so "one hypothesis" or "possibly" would be consistent.
- The S1 card's EQIP label is changing from "$74 (unverified)" to "~$74, third-party figure" in the parallel wording
  pass, which matches the secondary status. Check this in the final screenshots.
- The Method view shows v1 Raccoon test CSI 0.33. `VALIDATION.md` §2 shows 0.32 (different rounding or count basis).
- The first-ever-ban IPR URL (2025-06-20) and the EPA MCL page are cited but could not be re-opened from this session
  (hosts blocked). Both claims rest on primary quotes already in `docs/facts.json` (`ban_2025_start`, `mcl_mgL`).

## Resolved since the last check

- **2026 "42-day ban"**: the app hero and KPI now read "23 days for homes, 42 for businesses" (`banWords()` in
  `web/js/city.js`, keyed on the `ban_2026_days` label). 2025 reads "up to 56 days (homes: 40)".
- **Provisional data caveat**: it now says provisional from 2026-06-02 (`meta.json`).
- **N2O wording**: S1 now says "Lower indirect N2O ...; direct field N2O did not change", which matches Parkin 2016.
- **"At the intake"**: the KPI and lede now say "Raccoon River at Van Meter (upstream of the intake)".
- **"Fertilizer farmers already paid for"**: replaced in the Replay text by "nitrogen that would otherwise leave the
  fields (part fertilizer, part soil N)".
- **Scenario numbers**: README, VALIDATION and PITCH match `scenarios.json` (2026-11-15 run). The earlier proxy-on
  run (23 plant days, 5-41; $350k) is retired.
