# Field to Faucet: claims register

Every number shown in the web app (`web/`) or in `PITCH.md`, with its value, range, where it appears, its source and how
well it is verified. Values were checked against the files on 2026-11-14/15 (USGS data through 2026-11-13).

**Verification status**
- **primary**: the number was read on the original source page or dataset (see `docs/facts.json` → `quote`, `checked_at`).
- **secondary**: from a source that quotes the original, which we could not open (blocked host or no access).
- **derived**: our arithmetic on primary numbers (for example ban days counted from primary start and end dates), or our
  count on primary measured data (USGS).
- **derived-from-our-model**: an output of our models; see `VALIDATION.md` for how far it is tested.
- **unverified**: not confirmed. Unverified facts are dropped by the exporter and not shown (EQIP 328 rate).

**Where shown (abbreviations)**: KPI = city view "record, with sources" tiles; Hero = city view headline and impact
slider; Replay = city view 2025/2026 replay; River = river chart; Map = hotspot map and list; Outlook = 14-day outlook;
Farmer = field panel and leak calendar; Cards = strategy cards; Method = "How we know" view; P1-P7 = pitch slides;
V = video script.

Most source URLs below are stored with the value in `docs/facts.json` (exported to `web/data/facts.json`), so the app
can link each tile to its source.

---

## 1. Water-utility facts

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| People served by Central Iowa Water Works | more than 600,000 ("600k" on the tile) | KPI, Hero, P1, P2, P5, V | https://ciww.gov/central-iowa-water-works-returns-to-everyday-water-stewardship-as-nitrate-removal-facility-concludes-193-days-of-operation/ (`water_people_served`) | primary | IPR calls it "one in five Iowans" (not shown) |
| 2025 nitrate-removal plant run | 112 days (10-18 Apr and 28 Apr-8 Aug 2025) | KPI, P2, P5 | https://www.kcci.com/article/central-iowa-water-works-lifts-lawn-watering-restrictions-water-quality-nitrates/65789527 (`plant_days_2025`) | primary | CIWW's "102 days through 29 Jul" agrees |
| 2025 cost of removing nitrate | $2.2M ($1.6M operations and maintenance + $0.6M capital) | KPI, P2 | https://ciww.gov/what-is-the-nitrate-removal-facility/ (`plant_cost_2025_usd`) | primary | |
| 2025 plant O&M cost | $1.6M | Replay cost note, P5 note | same page (`plant_om_cost_2025_usd`) | primary | low end of cost per day |
| Plant cost per operating day | $14,286-16,000 per day | Replay (cost range basis), Method | low = $1.6M / 112 days (derived); high = "about $16,000 a day" at full capacity (`plant_cost_per_day_usd`, primary) | derived / primary | partial operation can cost as little as about $4,000/day (same page); avoided days are shoulder days, so the $ range may be high |
| 2026 plant run (record) | 193 days (6 Jan-2 Mar and 9 Mar-23 Jul 2026) | KPI (2026 replay), P2, Method | CIWW URL above (`plant_days_2026`) | primary | not continuous; never say "193 straight days" |
| Previous record run | 177 days, 2015 | P2 speaker note | https://www.kcci.com/article/central-iowa-water-works-nitrate-removal-facility-turns-off-running-for-112-days-so-far-this-year/65670201 (`plant_days_record_prior`) | primary | 2026 set a record for **duration**, not concentration |
| 2026 cost if replay year = 2026 | $2.8M-3.1M (193 days × $14,286-16,000) | KPI (2026 replay) | arithmetic in `web/js/city.js` | derived | no full-year 2026 cost has been published; Q1 2026 O&M was about $660k (`plant_om_cost_2026_q1_usd`) |
| 2025 lawn-watering ban | 56 days for all customers (12 Jun-7 Aug 2025); 40 days for homes (released 22 Jul) | KPI, P2, P5 | `ban_2025_days` from primary dates `ban_2025_start` (https://ciww.gov/ciww-resumes-commercial-irrigation-continuing-the-phased-exit-from-the-stage-iii-watering-ban/), `ban_2025_residential_eased`, `ban_2025_end` (KCCI) | derived | CIWW's first-ever ban; all restrictions ended 15 Aug |
| 2026 lawn-watering ban | 42 days for businesses and governments (8 Jun-20 Jul 2026); 23 days for homes (released 1 Jul) | KPI (2026 replay), P1, P2 | `ban_2026_days` from `ban_2026_start` (https://ciww.gov/central-iowa-water-works-issues-stage-3-water-warning/), `ban_2026_residential_eased`, `ban_2026_end` | derived | never say "42-day ban for everyone" |
| Bans in two consecutive summers | 2025 (first ever) and 2026 | P1, V | `ban_2025_start`, `ban_2026_start` | primary | |
| EPA drinking-water limit for nitrate | 10 mg/L as N | everywhere (charts, KPI labels, footer) | https://www.iowapublicradio.org/ipr-news/2025-06-25/nitrate-levels-central-iowa-water-des-moines (`mcl_mgL`) | primary | |
| 2025 ban-lift rule | at least one source ≤ 10 mg/L | Method (ban proxy) | https://ciww.gov/stage-iii-daily-updates/ (`ban_lift_rule`) | primary | used as the ban proxy threshold |
| Lawn watering share of summer demand | up to 40% | Method / scenario caveat | https://ciww.gov/why-is-ciww-implementing-a-lawn-watering-ban/ (`lawn_watering_share_pct`) | primary | |
| Stage III trigger | demand above 90% of treatment capacity | Method / scenario caveat | IPR 2026-06-09 (`stage3_trigger_demand_pct`) | primary | |
| Removal plant size vs demand | 10 million gallons/day vs 70-80 MGD normal demand | P2 speaker note | CIWW FAQ (`plant_capacity_mgd`), IPR (`nrf_vs_demand`) | primary | why the plant output is blended |
| Plant expansion capital | about $40M estimated; $25M appropriated by the state | Replay cost note ("~$40M expansion"), P7 note | https://www.kcci.com/article/kcci-investigates-12-billion-in-central-iowa-water-works-projects-coming/73659187 (`capital_nrf_expansion_cost_usd`, `capital_state_grant_usd`) | primary | not avoided by the scenarios; never present the $1.2B CIWW program as a nitrate cost |
| Share of Iowa stream N from nonpoint sources | 92% (INRS Table 1: 93%) | P1 speaker note; scenario prior s | https://www.nutrientstrategy.iastate.edu/sites/default/files/documents/1%202025%20INRS%20Executive%20Summary%20and%20Section%201_Policy%20-%20FINAL%20February%204%202025.pdf (`inrs_nonpoint_share_pct`) | primary | say "nonpoint (mostly agricultural)", not "agriculture" |

## 2. River measurements (our analysis of USGS data)

USGS NWIS daily values, parameter 99133 (nitrate + nitrite, mg/L as N) and 00060 (discharge), sites 05484500 (Raccoon
River at Van Meter) and 05482000 (Des Moines River at 2nd Ave). Fetched by `pipeline/p02_nwis.py` into
`data/processed/nwis_daily.parquet`; counts are on days with a measurement.

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Raccoon days above 10 mg/L, 2025 | 115 of 356 measured days (first 26 Mar; still above 10 on 31 Dec) | KPI, Hero, Replay, P2, P5, P6 | https://waterdata.usgs.gov/monitoring-location/05484500/; `web/data/scenarios.json → by_year.2025.observed` | derived (primary USGS data, our count) | USGS-approved data |
| "about 1 day in 3" | 115 / 356 | KPI lede, Replay | same | derived | |
| Des Moines River days above 10 mg/L, 2025 | 105 of 287 measured days (9 Apr-6 Aug) | Replay, P2 note, P6 | https://waterdata.usgs.gov/monitoring-location/05482000/ | derived | Jan-Feb 2025 not measured, so a lower bound |
| Raccoon / Des Moines days above 10, 2026 (to 13 Nov) | 176 of 298 / 158 of 314 measured days | Replay (2026), River, P2 note | USGS, `scenarios.json → by_year.2026.observed` | derived | about 55% of 2026 values are provisional (from 2 Jun 2026) |
| 2025 peak daily mean | Raccoon 18.4 mg/L (7 Jun); Des Moines 17.0 mg/L (12 Jun) | River, P6 note | `model/out/metrics.json → crisis_2025` | derived | IPR reports 20.55 / 17.15 (a different averaging); do not claim a record concentration |
| 2026 Raccoon peak daily mean | 18.6 mg/L (28 May 2026) | River | USGS dv (`raccoon_2026_peak_mgL`) | primary (provisional data) | |
| Combined nitrate load at the two gauges, 2025 | 55,300 t N (Raccoon 18,600; Des Moines 36,600) | Replay (scenario baseline) | `scenarios.json → by_year.2025.observed.load_tN`; measured flow × gap-filled concentration (`model/m07_scenarios.py`) | derived | gap-fill error ≤ 2.5% of annual load in most years |
| River load per row-crop acre reaching Van Meter | about 17 lb N/acre/yr (2016-2025 mean 16.5; 1.2 in 2021 to 34.4 in 2016) | Cards (S0 evidence) | `model/out/basin_index_check.json → calibration`; `model/m05_fields.py` | derived | load delivered to the gauge, after in-stream losses |
| Last measured value at outlook issue | Raccoon 11.6 mg/L, Des Moines 11.1 mg/L (13 Nov 2026) | Outlook | USGS dv, `web/data/outlook.json → last_obs` | primary (provisional) | |
| Measured days above 10 "in view" | computed live from `river_series.json` | River note | USGS | derived | |
| Gauge drainage areas | 3,441 sq mi (Van Meter); 6,245 sq mi (2nd Ave) | README | https://waterservices.usgs.gov/nwis/site/?format=rdb&sites=05484500,05482000&siteOutput=expanded&siteStatus=all | primary | |
| Watershed area modelled | about 25,000 km² (Raccoon 9,004 + Des Moines 16,225 km² of WBD HUC-12s; 290 HUC-12s) | P3 note, README | USGS WBD via `pipeline/p01_wbd.py` (`data/processed/huc12.parquet`) | derived | Des Moines basin extends into Minnesota |
| Row crops share of the basins | about 75-78% of land every year (10-year means: Raccoon 75.6%, Des Moines 77.7%) | README | USDA CDL via `pipeline/p06_cdl_shares.py` | derived | |
| Field drill-down coverage | 1,769 forty-acre (400 m) fields in 10 HUC-12s (846 km²), HLS tile 15TUG, 2020-2026 | Farmer, P3, README | `pipeline/p10_focus_area.py`, `p12_fields.py` | derived | a "field" is a grid cell, not a surveyed field |
| MODIS record length | 8-day cadence (Terra + Aqua 16-day composites) from 2015-07 (v1) and 2011-07 (v2) | P3 note, README | `pipeline/p09_modis_cover.py`, `model/m06_history.py` | derived | Jul-Nov 2025 filled from HLS |

## 3. Model results

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| v1 out-of-time skill (test 2023-25) | NSE 0.62 Raccoon, 0.56 Des Moines; climatology 0.30 / 0.27 | Method, P6 | `model/out/metrics.json → sites.<site>.splits.test`; `model/m02_river_model.py` | derived-from-our-model | the split was fixed before fitting |
| "about 62% / 56% of the ups and downs" | plain-language NSE | Method | same | derived-from-our-model | |
| 7-day persistence NSE (test) | 0.77 Raccoon | Method | same | derived-from-our-model | uses last week's measurement |
| v1 80% band coverage (test) | 66% (should be 80%) | Method | same | derived-from-our-model | Des Moines 64% |
| 2025 miss, v1 | 6 modelled vs 115 measured days above 10 (Raccoon); 10 vs 105 (Des Moines); v1 upper bound above 10 on 121 days | Method, P6 | `metrics.json → sites.<site>.crisis_2025.gbm` | derived-from-our-model | |
| Year-level offset 2025 | measured ≈ 1.7× (Raccoon) and 2.1× (Des Moines) what drivers explain | Method, River "Honest limit" line ("test NSE ~0.6 … about 1.7-2.1×"), meta caveat ("about twice") | `web/data/validation.json → level_ratio_obs_over_model` (1.68, 2.07) | derived-from-our-model | cause unresolved; legacy N is a hypothesis |
| v2 (post-hoc) 2025 | 83 of 115 days (Raccoon); 10 of 105 (Des Moines) | Method, P6 | `metrics.json → v2.sites.<site>.crisis_2025` | derived-from-our-model | built after seeing the miss |
| v2 test NSE (post-hoc) | 0.78 Raccoon, 0.59 Des Moines | Method, VALIDATION | `metrics.json → v2` | derived-from-our-model | |
| Blind 2013 check (pre-registered) | measured 92 days above 10; v2 81; v1 features 80 | Method, P6 note | `metrics.json → v2.sites.05484500.blind_2013` | derived-from-our-model | most of the gain is the longer record |
| Strict check 2012-19 → 2020-25 | ln-RMSE 0.75 (v2) vs 0.99 (v1 features), Raccoon; 1.20 vs 1.25 Des Moines | VALIDATION, P6 note | `metrics.json → v2.sites.<site>.strict_check` | derived-from-our-model | |
| 14-day outlook vs "no change" (test) | squared error 20% better at 1 week, 25% at 2 weeks (Raccoon); 37% / 17% (Des Moines) | Outlook text, Method, P6 | `metrics.json → outlook.sites.<site>.test_2023_2025.h7/h14` | derived-from-our-model | no weather forecast used |
| No probability skill at 14 days | Brier skill vs probabilistic persistence +0.03 (Raccoon), −0.04 (Des Moines) | Outlook text, Method, P6 | same | derived-from-our-model | |
| Outlook issued 14 Nov 2026 (Raccoon) | 11.6 → 11.3 mg/L by 27 Nov (8 in 10: 9.4-12.5); about 12 of 14 days above 10; day-14 chance 81% | Outlook | `web/data/outlook.json`; `model/m04_outlook.py` | derived-from-our-model | Des Moines: 9.9 (8.8-12.3), about 11 days |
| Outlook drivers (as of 11 Nov 2026) | root-zone wetness 0.63, 100th percentile; rain last 7 days 0.2 mm, 21st percentile; bare cropland 75%, 10th percentile (MODIS 27 days old) | Outlook | `outlook.json → drivers` (NASA POWER, MODIS) | derived | percentiles against the same ±7-day window in 2016-2025 |
| Plant proxy test | fitted to 2025: 106 proxy days vs 112 reported; tested on 2026 without refit: 157 vs 193 (daily F1 0.90) | Method, meta caveat, P6 note | `scenarios.json → thresholds.calibration.plant` | derived-from-our-model | rule: 7-day mean of the two rivers' average > 10.2 mg/L |
| Ban proxy test | 2025: 66 vs 56 (F1 0.87); 2026: 40 vs 42 (F1 0.81) | Method | `thresholds.calibration.ban` | derived-from-our-model | starts too early; indicative only |
| Median field leak (focus area, 1,769 fields) | 13.7 lb N/acre/yr long-run mean; across fields 8.8-20.0 (5th-95th pct); single-year range for the median field 0.8-30.6 (10th-90th pct) | Farmer, P4 | `model/out/basin_index_check.json → fields`; `web/data/field_detail/*.json`; `model/m05_fields.py` | derived-from-our-model | per-field values shown in the panel; not validated at field scale |
| Field leak percentile | "leaks more than N% of fields nearby" | Farmer | `fields.geojson → leak_pctile` | derived-from-our-model | |
| Poorly drained vs well-drained fields | 1.35× more leak | README, P4 note | `basin_index_check.json → fields.poorly_vs_well_p50_ratio` | derived-from-our-model | follows from the tile multiplier prior |
| Leak timing on the average field | 91% of modelled leak Oct-May; 54% Apr-Jun | Cards (S0, S1 why), P3 | `notes/fields_model.md` §3 from `field_scores.parquet` | derived-from-our-model | |
| Fields bare (HLS) | 92% of Oct-May and 63% of Apr-Jun, 2020-2025 | Cards (S0 satellite evidence), P3 | `web/data/strategies.json` (from `hls_field_ts`/`field_month`) | derived (NASA HLS) | |
| Big-storm days in Apr-Jun | 34% of the year's days ≥ 25 mm on the average field | Cards (S1 why) | `strategies.json`, NASA POWER | derived | POWER smooths storm peaks |
| Winter living cover seen by HLS | 2.5% of field-winters (2021-2026); 9% of fields at least once | Cards (S0, S1), P3 note | `strategies.json`; `notes/fields.md` (0.8-4.2% per year; 8.8% any year) | derived (NASA HLS) | lower bound: thin rye is missed; statewide adoption about 17% |
| Top 6 Raccoon hotspots | 8.8% of basin area, 15.1% of modelled leak | Map side list | `web/data/huc12.geojson` (`share_of_basin_leak`, `area_km2`), computed in `city.js` | derived-from-our-model | ranking not validated (no sub-basin gauges) |
| Focus area rank | 10 HUC-12s rank 17-105 of 105 in the Raccoon | README | `huc12.geojson` | derived-from-our-model | |
| HUC-12 popup values | row-crop share, poorly drained share, bare+wet days, share of leak, rank | Map | `huc12.geojson` (CDL, SSURGO, MODIS, POWER) | derived / derived-from-our-model | |
| Index vs measured annual load | r = 0.75 (n = 20), but water alone 0.79-0.83 | VALIDATION, P6 note | `basin_index_check.json` | derived-from-our-model | partial r of the bare term −0.39 |
| HLS vs MODIS | deseasonalized r 0.63; HUC-12 ranking r 0.94 | VALIDATION | `data/processed/hls_vs_modis.json` | derived | |
| POWER vs IMERG on storm days | r 0.62, volume ratio 1.01, slope 0.48 | VALIDATION, P3 note | `data/processed/imerg_vs_power.json` | derived | |

## 4. Scenario results (2025 replay unless stated)

Source for all rows: `web/data/scenarios.json → by_year.<year>.levels[x].avoided` (p50 and 10th-90th percentile of 4,000
draws), written by `model/m07_scenarios.py`. Lever: X% **additional** upstream row-crop acres with a cereal-rye-type
living cover Oct-May, on top of today's adoption, in both intake basins. Impact basis: each day's **measured** nitrate
cut by a fraction that mixes half trial prior and half learned river response. Status for all: **derived-from-our-model
(counterfactual, not validated)**.

| claim | value (range) | where shown | notes |
|---|---|---|---|
| Removal-plant days avoided, 25% | **23 (5-41)** | Hero, Replay, P5, V | proxy baseline 120 (106-134) days vs 112 reported |
| Operating cost avoided, 25% | **$350k ($73k-620k)** | Hero, Replay, P5 | O&M only; capital not avoided |
| Ban days avoided, 25% | **23 (9-31), indicative** | Hero, Replay, P5 | ban proxy 68 days vs 56 reported; least certain |
| Raccoon days above 10 avoided, 25% | 8 (2-16); "about 107 days (99-113) instead of 115" | Replay, P5 | the Raccoon sat far above 10, so few days flip |
| Des Moines River days above 10 avoided, 25% | 19 (5-36) | Replay (other site), P5 note | |
| Nitrogen kept out of the rivers, 25% | 6.5 million lb (2.1-10.0 million) | Replay sentence, P5 | nitrate that would have reached the two gauges; field-edge retention larger |
| Load cut at the gauges, 25% | 2,930 t N (940-4,550) of 55,300 | Replay (data), P5 note | |
| 10% adoption, 2025 | plant days 7 (2-16); $105k ($29k-237k); ban days 9 (1-13); Raccoon days 2 (0-4) | Replay slider | |
| 50% adoption, 2025 | plant days 46 (11-72); $690k ($159k-1.08M); ban days 32 (13-46); Raccoon days 16 (5-45) | Replay slider | 50% additional ≈ two-thirds of acres covered |
| 2026 replay, 25% (partial year) | Raccoon days 5 (3-22); Des Moines days 29 (11-57); plant days 19 (7-51); $282k ($110k-768k); ban days 15 (1-26) | Replay (2026) | 2026 data partly provisional |
| Path-only results, 2025, 25% (Raccoon days above 10) | trials only 9 (1-21); learned model only 7 (3-11) | Method / P5 speaker note | `method_detail.path_only_avoided` |
| Plain-language slider label | "1 in 4 more upstream fields" = 25% | Hero, P5, V | |

## 5. Agronomy and trial priors

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| Cereal rye cuts drainage nitrate (INRS 2024 update) | 28% mean, SD 26 (draw 10th-90th: 6-54%) | Cards (S1), Replay method, scenarios prior, P4, P5 | https://www.nutrientstrategy.iastate.edu/sites/default/files/documents/INRS_2024_PracticeEffienciesNitrogen_U20240319.pdf (Table 1) | primary | concentration cut, not a field-load guarantee |
| Rye, older INRS table | 31%, SD 29 | Cards (S1) | INRS Feb 2025 Section 2 (`inrs_cover_rye_pct`) | primary | the Feb 2025 edition still prints the old table |
| Extended rotation, 4+ years (2024 update) | 27%, SD 25 (older table 42%, SD 12); 3-year 15%, SD 34 | Cards (S2), P4 | INRS 2024 PDF; INRS 2025 Section 2 (`inrs_ext_rotation_pct`) | primary | |
| Land retirement (CRP) | 85%, SD 9 on converted land | Cards (S3) | INRS 2025 Section 2 (`inrs_crp_pct`) | primary | S3 whole-field effect = 10% × 85% ≈ 8.5% |
| Saturated buffer / bioreactor (2024 update) | 45% / 24% of treated drainage | Cards (S3 gaps) | INRS 2024 PDF (`inrs_2024_update`) | primary | treated water only |
| USDA-ARS 14-year rye experiment near Ames | 57% lower nitrate load (concentration 59%) | Cards (S1), P4 note | https://www.ars.usda.gov/research/publications/publication/?seqNo115=333537 (`kaspar_rye_pct`) | primary | |
| Rye at other Iowa sites | 15-48% lower nitrate | Cards (S1) | https://www.sare.org/wp-content/uploads/Tom-Kaspar_Session-7.pdf (`kaspar_other_sites_pct`) | secondary | SARE host blocked |
| Rye before soybean, yield | no yield loss in 27 of 28 Midwest location-years | Cards (S1), P4 | https://www.ars.usda.gov/research/publications/publication/?seqNo115=405613 (`rye_before_soybean_yield`) | primary | |
| Rye before soybean, farmer trials | no detectable effect in 20 of 29 trials; gain in 8 | Cards (S1) | Practical Farmers of Iowa (`E1_soy_yield_pfi`, `shared/evidence/evidence_priors.json`) | secondary | |
| Long-term cover adopters, soybean yield | about 3.5% lower (satellite study, ≥ 3 years of covers) | Cards (S1 yield risk) | Deines et al. 2023, https://doi.org/10.1111/gcb.16489 (`E1_soy_yield_deines`) | secondary (abstract only) | observational |
| Average Iowa corn/soy acre N loss | about 30 lb N/acre/yr (15-50) | Cards (S0) | https://stories.cals.iastate.edu/2015/11/the-science-behind-nitrate-transport (`isu_lbN_acre_yr`) | secondary | host blocked |
| Statewide cover-crop adoption | about 17% of Iowa corn+soy acres (3.87M acres, 2024) | Replay method, meta caveat, P5 note | https://www.iowafarmbureau.com/Article/Farmers-expanding-cover-crop-notill-acres-across-the-state (`iowa_cover_share_pct`) | secondary | IDALS confirms only "nearly 4 million" |
| Marsden extended-rotation trial | corn +4%, soybean +9%; synthetic N −80 to −86%; herbicide −88%; profit similar or greater | Cards (S2) | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0047149 (Davis et al. 2012); https://www.ars.usda.gov/research/publications/publication/?seqNo115=282234 | primary / full text | used manure and 2003-2011 prices |
| Diverse rotations in drought | drought-year losses cut 14-90% | Cards (S2) | Bowles et al. 2020, https://par.nsf.gov/servlets/purl/10331499 | full text | no Iowa site |
| Rye and erosion | interrill erosion about half, rill about 90% lower | Cards (S1 soil health) | Kaspar 2001 via https://store.extension.iastate.edu/Product/pm1999-pdf (`E1_erosion_kaspar2001`) | secondary | |
| Cover crops and infiltration | about +35% | Cards (S1) | Basche & DeLonge 2019, https://pmc.ncbi.nlm.nih.gov/articles/PMC6752860/ | full text | Kaspar 2001: only 1 of 3 Iowa years |
| Cover crops and soil carbon | about +4% (non-legume covers) | Cards (S1) | He et al. 2025, https://doi.org/10.1038/s44264-025-00050-8 | full text | |
| Rye and N2O | lower indirect N2O via less nitrate leaching; direct N2O not significantly changed | Cards (S1) | Parkin et al. 2016, https://doi.org/10.2136/sssaj2016.04.0120 | abstract | card wording "lower total N2O" is stronger than the abstract; see open questions |
| Prairie strips (STRIPS) | groundwater nitrate about −72%, runoff total N about −70% (non-tiled watersheds); sediment about −95%; total P −77%; runoff −37%; yield per cropped acre unchanged | Cards (S3) | https://news.iastate.edu/news/2017/10/03/strips10years (secondary); Schulte et al. 2017, https://www.fs.usda.gov/nrs/pubs/jrnl/2017/nrs_2017_schulte_001.pdf (full text) | secondary / full text | runoff-N CI includes zero; not comparable with tile practices |
| Tile delivery multiplier | 1-4× (central 2.5) | README, VALIDATION | McIsaac & Hu 2004 via David et al. 2010 (`tile_delivery_mcisaac_hu`) | secondary | the 2.7-4 ratio is our arithmetic |
| Living-cover leak factor ε | 0.232 (cover fields leak 28% less) | README, VALIDATION | calibrated on 187 HLS-detected cover field-years to INRS 28% | derived-from-our-model | |
| Row-crop share of river nitrate s | 0.76-0.89 (central 0.83) | Replay priors, README | INRS nonpoint 92% × CDL row-crop share (`basin_index_check.json`) | derived | |
| N kept per acre, median field | S1 rye before soy 1.7 lb/acre/yr (single year 0-4.5; wet 2016: 9.2); S2 4-yr rotation 3.7 (0.2-9.9; 8.9); S3 prairie 10% 1.2 (0.1-2.5; 2.8) | Cards (per field), P4 | `web/data/field_detail/*.json → strategies`; `model/m06_strategies.py` | derived-from-our-model | trial efficiency × the field's modelled leak; counted at the gauge |

## 6. Program and cost numbers

| claim | value (range) | where shown | source | status | notes |
|---|---|---|---|---|---|
| NRCS EQIP 340 (cover crop) | about $74/acre (FY2026 Iowa, single species); $89/acre historically underserved | Cards (S1 who pays), P4 | https://soilpractice.com/guides/eqip-csp-after-2025-budget-law/ (`eqip_340_usd_ac`) | secondary | NRCS booklet unreachable; card says "confirm with your NRCS office" |
| NRCS EQIP 328 (conservation crop rotation) | rate hidden | Cards (S2) | (`eqip_328_usd_ac`) | unverified | not shown |
| IDALS cover-crop cost-share | $30/acre first-time, $20/acre returning, up to 160 acres | Cards (S1), P4 | https://iowaagriculture.gov/news/cover-crop-cost-share-program-2026 | primary | |
| Greater Des Moines Watershed program | $25/acre on up to 500 acres, 22 counties | Cards (S1), P4, P7 | https://iowaagriculture.gov/news/greater-dsm-watershed-program | primary | stackable with the state program |
| Crop-insurance cover-crop discount | $5/acre | Cards (S1), P4 | https://iowaagriculture.gov/news/crop-ins-discount-prog-signup-12-25 | primary | not on acres with other cover-crop cost-share |
| Rye cost | $12-27.50 per acre per year ($24-55 per planting, every other fall) | Cards (S1), P4 | drilling $9-25 (avg $19.05): https://www.extension.iastate.edu/agdm/crops/pdf/a3-10.pdf; seed $15-30 (about $25): https://www.extension.iastate.edu/agdm/crops/pdf/a1-92.pdf | primary (inputs) / derived (per-year) | termination pass not included |
| Prairie-strip cost | $26-33 per treated acre per year; with CRP CP-43 about 75% lower, $7-8 | Cards (S3) | https://strips.nrem.iastate.edu/chapter-5-economics (`strips_cost_usd_treated_ac`, `strips_crp_cost_reduction_pct`) | secondary | host does not resolve here |
| Extended-rotation cost | not quantified | Cards (S2) | Marsden profit similar or greater | – | not ranked as $0 |
| Nitrogen price | $0.53-0.70 per lb N (central $0.67) | Cards (fertilizer value) | low: ISU A1-88 July 2026 budget (primary); central/high: USDA AMS Iowa anhydrous $1,096/ton, https://mymarketnews.ams.usda.gov/filerepo/sites/default/files/2863/2026-04-27/1321477/ams_2863_00161.pdf (`fert_price_usd_lbN`, secondary) | primary / secondary | |
| Fertilizer value of N kept, median field | S1 $1.02, S2 $2.28, S3 $0.72 per acre per year | Cards, P4 | `field_detail → strategies.<S>.fert_value_usd_ac.mean` | derived-from-our-model | upper bound; N kept ahead of soybean has little value to that soybean crop |
| Scenario cost per plant day | $14,286-16,000 | Replay | see section 1 | derived / primary | |

---

## Open items

- The S1 soil-health line "Lower total N2O (via less nitrate leaving)" is slightly stronger than the Parkin 2016 abstract
  (direct N2O not significantly changed; estimated indirect N2O lower). Suggested wording: "Less nitrate leaving, so
  lower indirect N2O (direct N2O unchanged)".
- Field leak and N kept are shown as the long-run mean (13.7 lb/acre/yr for the median field), with the single-year
  10th-90th percentile as the range (`meanBand()` in `web/js/util.js`). Do not quote the single-year p50 (10.8) as the
  headline.
- With the 2026 replay year selected, the hero line reads "600,000+ people faced a 42-day lawn-watering ban". 42 days
  applies to businesses and governments; homes were released after 23 days (`ban_2026_days` range 23-42). The KPI tile
  shows "(homes: 23)", but the hero sentence should too (facts notes: never "42-day ban for everyone").
- App caveat "USGS nitrate data from about mid-2025 on are provisional" is out of date: provisional values start
  2026-06-02 at both sites.
