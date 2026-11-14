# Module: pumping (Kansas WIMAS reported water use)

Owner files: `pipeline/pumping_fetch.py`, `pipeline/pumping_process.py`, `data/processed/wimas_use.parquet`,
`data/processed/wimas_county_year.parquet`, `data/processed/wimas_summary.json`, this note.

## Source
Kansas **WIMAS** (Water Information Management and Analysis System), a joint KGS and Kansas Dept. of Agriculture, Division of
Water Resources (DWR) system: https://geohydro.kgs.ku.edu/geohydro/wimas/ . The water-rights data are from the weekly WIMAS build
dated **11/08/2026**. Water-use reports are filed every year under K.S.A. 82a-732 and quality-controlled by DWR/KWO.
Code tables (crop, irrigation system, water-use report codes) come from KGS OFR 2005-30, the WIMAS v5 user manual:
https://geohydro.kgs.ku.edu/geohydro/ofr/2005_30/wimas_ofr2005_30_manual.htm

No bulk WIMAS export turned up on data.kgs.ku.edu. Its landing page just links back to the WIMAS query site, so we scraped the
WIMAS query site directly.

### How the scrape works (ColdFusion, needs a cookie session; see `pumping_fetch.py`)
1. `GET index.cfm` sets the CFID/CFTOKEN/JSESSIONID cookies.
2. `POST query_setup.cfm wimas_accept=Accept` with Referer index.cfm accepts the disclaimer. Without the cookie and Referer the
   server answers "browser must be set to allow cookies".
3. `POST query_setup.cfm` (multipart) with these fields:
   - `county='XX'`
   - `umwf='IRR'` and `umwf='MUN'`
   - `a_v=on` (primary appropriated/vested rights)
   - `source=n` (groundwater and surface water)
   - `user_email`, a required field. We send the generic, non-personal placeholder `water-clock-hackathon@example.com`.

   The server replies with a 302 to `query_results.cfm`.
4. Three downloads in the same session. Each `download.cfm` page links a text file on `maps.kgs.ku.edu`, which the proxy refuses
   with 403. The identical file is served at `https://geohydro.kgs.ku.edu/geohydro/downloads/<file>`.
   - `download.cfm?type=main&active=no` gives water right x point of diversion (PD): PLSS location, lon/lat, GMD, basin.
   - `qty_sum.cfm`, then `download.cfm?type=qty`, gives authorized quantity per right x PD (AF).
   - `POST wuse_trends.cfm` (wuse_start, wuse_end, T_Submit), then `download.cfm?type=wuse&syear=&eyear=`, gives one water-use
     report record per right x PD x year. Fields include af_used, acres_irr, crop_code, type_system, meter info, wur_code and
     depth to water.
5. The water-use query runs on the server and is slow. Two problems came up:
   - A full 1990-2025 request for large counties (Finney, Gray, Haskell) outlived the proxy connection:
     `ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))`.
     Counties with more than 800 PDs are now requested in year windows of `36*700/n_PD` years.
   - If a window returns HTTP 500, it is split in half. A single year that still fails is retried township by township. If it
     still fails, the year is recorded as missing.

The raw files are cached in `data/raw/wimas/<fips>_{main,qty,wuse}.txt` (gitignored, about 200 MB of text). The fetch logs are
`fetch_run1.log`, `fetch_run2.log` and `fetch.log` in the same folder.

Selection: all 26 contract counties; rights whose use made of water is irrigation (IRR) or municipal (MUN); both groundwater (G)
and surface water (S).

## Outputs

### `data/processed/wimas_use.parquet` (621,295 rows; 23,454 PDs: 22,880 irrigation, 677 municipal; 1990-2025)
Key: (`pdiv_id`, `year`, `use`). `use` is part of the key because a few PDs carry both IRR and MUN rights.

| column | meaning / units |
|---|---|
| pdiv_id | DWR point-of-diversion id (stable WIMAS id) |
| year | water-use year (calendar year of use) |
| use | `IRR` or `MUN` |
| wr_file_no | water right file number(s) at this PD, `;`-joined (e.g. `A 9017 00`) |
| n_rights | number of water rights with a record at this PD that year |
| lon, lat | PD location, decimal degrees NAD83, **as given by WIMAS** (100% present, so no PLSS conversion was needed) |
| county_fips | 5-character FIPS |
| gmd | "GMD1"/"GMD3"/"GMD4" from WIMAS's own PD attribute (official district membership of the PD); null outside a GMD |
| gmd_county | "GMD1"/"GMD3"/"GMD4" from the contract county list (whole counties) |
| source | `G` groundwater, `S` surface (`GS` if both) |
| aquifer_codes | WIMAS aquifer code(s) |
| af_reported | reported water use, acre-feet: sum of af_used over this PD's records that year |
| acres_irrigated | reported acres irrigated: sum over records |
| af_per_acre | af_reported / acres_irrigated, only when both are > 0 (feet) |
| flag_af_per_acre | True if af_per_acre is outside 0.05-5 ft (0.4% of rows; kept, but excluded from county AF/acre) |
| flag_acres_jump | True if acres_irrigated is more than 5x the PD's own median of positive reported acres (PDs with >= 3 such years). Likely typos or whole-right acres on one PD (e.g. Stevens PD 53793: 3,320 ac in 2002 at 0.16 ft). Kept, but excluded from county AF/acre |
| crop_code, crop_name, crop_group | WIMAS crop code; name from OFR 2005-30; group in {corn, sorghum, wheat, soybeans, alfalfa, cotton, pasture, multiple/other} |
| system_code, system_name | irrigation system (1 flood, 3 center pivot, 4 LEPA, 7 SDI, ...) |
| authorized_af | authorized quantity allocated to the PD in AF (see conventions below) |
| wur_code | water-use report code(s) (A metered AF, M gallons, E non-use with reason, ...) |
| metered | a meter unit was reported |
| depth_to_water_ft | depth to water reported on the use report (sparse). Values above 600 ft are source errors (max 9,301 ft; 99.9th percentile 582 ft) and are set to null |
| sect, twp, twp_dir, rng, rng_dir, plss_qq | PLSS location; plss_qq is the quarter calls from smallest to largest tract |

### `data/processed/wimas_county_year.parquet` (936 rows = 26 counties x 36 years, 1990-2025)

| column | meaning |
|---|---|
| county_fips, county_name, gmd | gmd is "GMD1"/"GMD3"/"GMD4" from the contract list |
| irr_af | total reported irrigation use (AF), groundwater and surface |
| irr_af_gw, irr_af_sw | split by source (surface matters only in Kearny, about 37 kAF/yr, and Hamilton, about 8 kAF/yr: Arkansas River ditches) |
| irr_acres | total reported acres irrigated (as WIMAS reports them; includes flagged rows) |
| irr_acres_gw | acres on groundwater PDs (pair with irr_af_gw) |
| irr_acres_jump_flagged | acres in rows with flag_acres_jump (subtract from irr_acres for a cleaned total) |
| af_per_acre | sum AF / sum acres over PD-years that report both AF > 0 and acres > 0 and are not flagged (feet) |
| n_pdiv | number of irrigation PDs reporting use > 0 |
| n_pdiv_reports | all PD-year records, including zero use |
| acres_\<crop\>, af_per_acre_\<crop\> | for single-crop PD-years (corn, sorghum, wheat, soybeans, alfalfa, cotton) |
| acres_crop_reported | acres with any crop code |
| mun_af | municipal use, AF |
| irr_authorized_af | current active authorized irrigation quantity for the county (AF; the same value in every year) |
| complete | False where the WIMAS query failed (Sherman 1998). Numbers are null there, not zero. |

### `data/processed/wimas_summary.json`
Coverage, GMD totals per year under both conventions (`gmd_year_county_based`: whole counties by the contract list;
`gmd_year_pd_attribute`: each PD's WIMAS gmd attribute), the checks against KGS TS22, and region AF/acre by crop.

### Which numbers to use for the groundwater clock
- Use `irr_af_gw` (or `source == "G"` in wimas_use), not `irr_af`. `irr_af` includes Arkansas River ditch diversions: the top
  af_reported rows are all surface-water PDs in Kearny (e.g. PD 19614, rights V FI 217 / V KE 76 / V KE 77, 68,279 AF in 2000).
  PD 19614 reports 8,000-9,999 ac in most years (a canal service area), so its 11,000 ac in 1998 is not a 10x typo.
- Use WIMAS acres together with WIMAS AF (af_per_acre is consistent with official application rates); do not divide WIMAS AF by
  Census acres.

## Aggregation conventions (verified)
- **Reported use.** The plain sum of `af_used` reproduces the WIMAS web "Water Use Trends" total for Greeley IRR groundwater in
  1990: 43,531.16 AF on the page against 43,531.14 AF from the export. Where a PD has overlapping rights, the use is reported on one
  right and the other rights carry 0 with `overlap_file` pointing to the reporting right. Summing therefore does not double count.
  Only 28 of 54,209 Finney PD-years with positive use have more than one positive record.
- **Join duplicates removed.** The wuse export repeats each record once per aquifer code and per special-use-area code of the PD.
  Rows belonging to such repeated groups: Finney 14,006 of 84,662, Kearny 18,334 of 42,166, Haskell 18,695 of 52,576. Across the region this is
  790,998 rows, 715,859 after collapsing. Without this step the region total was inflated by about 15% (2.82 vs 2.44 MAF/yr mean).
  WIMAS's own trend page may include these duplicates for counties that have them. This was only checked for Greeley, which has
  almost none.
- **Authorized quantity.** County totals = sum of `add_quant` (the additional, non-overlapping AF) over unique (wr_id, quant_id).
  This reproduces the WIMAS "Summarize Quantity" page exactly for Greeley IRR groundwater: 62,806.52 AF. For the per-PD
  `authorized_af`:
  - a quantity stored by PD (qstor_ind=2) goes to that PD;
  - a quantity stored by right (qstor_ind=1) is split evenly over that right's PDs.

  Per-PD values are therefore an allocation; county sums are exact. Authorized quantities cover active, non-dismissed rights as of
  2026-11-08 only, not historical authorizations.

## Coverage
- All 26 counties, 1990-2025.
- **One county-year is missing: Sherman (20181) 1998.** The WIMAS server returns `500 Server Error: Error Executing Database Query`
  for that year, and the township-by-township retry fails at township 9S. It is left null, with `complete=False`.
- 100% of PD-years have WIMAS lon/lat.
- 99% of irrigation PD-years with use > 0 carry a crop code. However, 49% of those are code 16 "More than one type of crop" or
  multi-crop combinations, so by-crop AF/acre rests on single-crop PD-years only. Shares of AF-reporting PD-years: corn 34%,
  alfalfa 7.7%, wheat 4.1%, sorghum 2.5%, soybeans 2.3%.
- 2025 is in the 11/08/2026 build with record counts similar to 2024. DWR releases quality-controlled use data in the fall after the
  use year, so treat 2025 as recent and possibly still being revised.

## Sanity checks
Mean reported irrigation use, 2000-2024 (from `wimas_county_year`):
- Largest counties, in AF/yr:

  | county | AF/yr | ft/ac |
  |---|---|---|
  | Finney | 276,700 | 1.28 |
  | Stevens | 225,600 | 1.31 |
  | Haskell | 197,300 | 1.10 |
  | Gray | 194,700 | 1.16 |
  | Kearny | 173,800 | 1.44 |

- Smallest: Logan, 7,400 AF/yr at 0.86 ft/ac.
- GMD totals use WIMAS's own PD GMD attribute and only PDs inside the 26 counties. Means for 1996-2016:

  | GMD | mean AF/yr | AF/acre, 2000-2024 |
  |---|---|---|
  | GMD3 | 1.87 million | 1.23 ft |
  | GMD4 | 0.42 million | 1.03 ft |
  | GMD1 | 0.21 million | 0.90 ft |

  GMD3 sits inside the 1-2 million AF/yr range given in the task brief.
- Against KGS Technical Series 22 (Whittemore, Butler & Wilson, *Status of the High Plains Aquifer in Kansas*, 1996-2016;
  https://www.kgs.ku.edu/Publications/Bulletins/TS22/HPA_tech_series22.pdf), which reports these trends in total annual water use
  for 1996-2016:

  | GMD | TS22 | ours (linear-fit change 1996->2016) |
  |---|---|---|
  | GMD1 | 34% decline | -35.7% |
  | GMD3 | 9.4% decline | -9.9% |
  | GMD4 | about 1% decline | -3.4% |

  TS22 also gives cumulative-use ratios: GMD3 "a little less than five times" GMD4 (ours 4.5x); GMD3 "ten times" GMD1 (ours 8.9x);
  GMD4 "about twice" GMD1 (ours 2.0x). The data reproduce the published district picture.
- Application depth: county AF/acre is 0.8-1.4 ft. Irrigated corn single-crop PDs run 1.0-1.6 ft as county means (1.26-1.57 ft in
  GMD3 counties, 1.01-1.27 ft in GMD4, 1.03-1.10 ft in GMD1). Region single-crop ratios for 2000-2024:

  | crop | ft/ac |
  |---|---|
  | alfalfa | 1.61 |
  | corn | 1.33 |
  | soybeans | 1.19 |
  | sorghum | 0.85 |
  | cotton | 0.84 |
  | wheat | 0.76 |

  This ordering is physically sensible. The "~1.5 ft/acre" figure in the brief matches GMD3 corn and alfalfa and GMD3 in wet/dry
  extremes (1.65 ft in 1990), but the long-run all-crop mean is lower, about 1.2 ft.
- Trend: GMD3 mean use fell from 1.76 MAF/yr (2005-2018) to 1.58 MAF/yr (2019-2024), a 10% drop. A 2023 KGS status report,
  seen only as a web-search summary, quotes "nearly 13%" for its own aggregation.

## Caveats
- Reported use is self-reported, mostly metered: TS22 says about 96% of irrigation wells in the GMDs had flowmeters as of 2013. We
  did no further QC beyond the af/acre flag, the acres-jump flag and nulling depth_to_water_ft above 600 ft.
- **Acres definition (important).** Acres irrigated are reported per right and PD. When several PDs serve one place of use, the
  same acres are reported on each record (in Finney, 89 multi-PD rights carry identical acres on every PD). Summed WIMAS acres
  are therefore **about 1.4x the Census of Agriculture irrigated land**: 2022 total over the 26 counties 1.97 M ac (WIMAS irr_acres) vs
  1.42 M ac (Census of Ag 2022 irrigated land, econ module county_context.json), ratio 1.39, ranging from 1.0x (Greeley) and
  1.1x (Morton, Logan) to 2.1x (Graham) and 2.3x (Stanton). 2022 was also a drought year, which lowers Census irrigated land. The plain sum is the official reporting
  convention: our 2014 totals by WIMAS PD gmd attribute match the official USGS/KDA 2014 Kansas irrigation water-use release
  (ScienceBase 577b8b5fe4b0ef4d2f4223a1, cached at data/raw/gmd/regions2014.csv) within 1-2%: GMD3 1,418,892 ac at 1.30 ft vs
  1,432,463 ac at 1.28 ft (1.841 vs 1.838 MAF); GMD1 and GMD4 also match in AF, acres and application rate (0.91 and 1.02 ft).
  For the rotation engine use WIMAS acres with WIMAS AF consistently, and show Census irrigated acres only as an alternative.
- The `gmd` attribute comes from WIMAS. County totals use the contract county list. The two differ for PDs outside GMD boundaries
  inside a listed county (44,528 PD-year rows have no WIMAS GMD) and for **Wallace (20199)**: the contract list puts it in GMD4,
  but about 90% of its irrigated acres are in GMD1 by the official polygons (econ check data/raw/gmd/county_gmd_check.json; WIMAS
  PD attribute agrees). Wallace has about 43k irrigated acres, roughly 20% of GMD1's acres and pumping. All processed files and
  model/common.py use the county-based GMD4 for Wallace; GMD-level totals by official membership are in
  `wimas_summary.json: gmd_year_pd_attribute`. The model owner should state the chosen convention in VALIDATION.md.
- Municipal use covers only MUN rights in the 26 counties (677 PDs). Industrial, stock and domestic uses were not fetched.
- The WIMAS disclaimer limits use of the data for selling property or services (K.S.A. 45-220(c)(2)). This non-commercial project
  is compatible with that.
