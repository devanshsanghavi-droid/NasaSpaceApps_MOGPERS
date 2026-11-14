# Module `rma`: USDA RMA Cause of Loss and Summary of Business

Scripts: `pipeline/rma_fetch.py` (downloads, 6 threads, caches to `data/raw/rma/`, skips cached files;
`--force-recent` re-downloads 2021+ because RMA keeps revising them) and `pipeline/rma_build.py`
(`--sanity` prints the checks below). Build takes about 75 s.

Raw snapshot: files downloaded 2026-11-14. RMA last updated colsom/sobcov/sobtpu 2022-2026 on 2026-11-09.
Raw cache: colsom 1989-2025, sobcov 2001-2025, sobtpu 2001-2025, plus the layout documents (about 360 MB).
The colsom 1989-2000 files are cached but not used, because the contract covers 2001-2025. Extending the outputs
would also need sobcov 1989-2000 and sobtpu 1999-2000, which have the same layouts.

## Sources (provenance)
- Cause of Loss with month: `https://pubfs-rma.fpac.usda.gov/pub/Web_Data_Files/Summary_of_Business/cause_of_loss/colsom_YYYY.zip`.
  Layout: `COL_Summary_of_Business_with_Month_All_Years.pdf` (as of 5/28/2026). 30 pipe-delimited fields, no header.
  The fields used are: 1 commodity year, 2 state FIPS, 4 county FIPS, 6 commodity code, 12 cause of loss code,
  28 net determined quantity, and 29 indemnity amount.
- Summary of Business by state/county/crop/coverage level: `.../state_county_crop/sobcov_YYYY.zip`.
  Layout: `SOB_State_County_Crop_with_Coverage_Level_1989_Forward.pdf`. 28 fields. The fields used are:
  18 quantity type, 19 net reported quantity, 21 liability, 22 total premium, 23 subsidy, and 27 indemnity (used for the cross-check only).
- Summary of Business by type/practice/unit: `.../state_county_crop/sobtpu_YYYY.zip`.
  Layout: `SOBTPU_External_All_Years.pdf`. 27 fields, with **CR-only line endings**. The fields used are:
  17 practice name, 20 net reporting level amount, and 21 reporting level type.

## Definitions
- **Year** is the commodity (crop) year (field 1), not the year of loss.
- **Crops**, by RMA commodity code. The names were checked in every year and file, with no mismatches:
  0041 CORN -> `corn`, 0081 SOYBEANS -> `soybeans`, 0011 WHEAT -> `wheat` (RMA has one wheat code for all classes),
  0051 GRAIN SORGHUM -> `sorghum`. `all` = every RMA commodity in the county, including Pasture/Rangeland/Forage
  (PRF, 0088), forage, specialty crops and Whole Farm (no acres).
  Popcorn (0043), hybrid seed corn (0062) and silage sorghum are not in `corn`/`sorghum`.
- **Cause codes** (colsom field 12; descriptions confirmed in field 13):
  - Drought = **11** "Drought"
  - Heat = **12** "Heat" + **62** "Hot Wind"
  - Excess moisture = **31** "Excess Moisture/Precipitation/Rain"
  - Not included: 13/14 irrigation failure, 44 Cold Wet Weather, 51 Flood, 01 Decline in Price, and
    55 "ARPI/SCO/ECO/STAX/MP/PACE Crops Only". Code 55 is area-based or endorsement indemnity that RMA does not assign
    to a peril. It counts in `indem_total_usd` but in no cause column, so the cause columns are a lower bound for
    area-plan losses (SCO/ECO payouts in drought years include some drought-driven loss).
- `insured_acres`: sobcov Net Reported Quantity, only where Quantity Type = "Acres". Records in tons, trees, colonies,
  clams or "Not Reported" (WFRP, nursery) are excluded. Endorsement plans (SCO, ECO, STAX-companion, HIP-WI, PACE) report 0
  net reported quantity, so their acres are not double counted.
- `liability_usd`, `premium_usd` (total premium before subsidy), `subsidy_usd`: sobcov fields 21-23, all plans and coverage levels.
  `subsidy_usd` is the **federal** premium subsidy only. State/private subsidy, the Additional Subsidy (Pandemic Cover Crop
  Program in 2021-2022) and the EFA discount are not included.
- `indem_total_usd`: sum of colsom indemnity over all causes. It equals sobcov indemnity within 0.03% in every year (see the cross-check).
- `indem_drought_usd`, `indem_heat_usd`, `indem_excess_moist_usd`: colsom indemnity for the causes above.
  Values can be slightly negative (claim reversals): 39 county rows for drought and 1 for the total, all small.
- `det_acres_drought`: colsom Net Determined Quantity for cause 11. These are acres on indemnified units attributed to drought,
  close to their planted acres, not acres of lost production. For `all`, the sum covers only commodities whose sobcov
  quantity type was Acres for every record that year, so tons and trees are not mixed in.
- `irrigated_insured_share`: from sobtpu, the share of acre-type net reporting amount whose practice name contains "IRR" but not
  "NON-IRR". That rule counts IRRIGATED, NFAC/FAC (IRRIGATED), ORGANIC ... IRR., RELAY CROPPING (IRRIGATED), LIMITED IRRIGATION
  and NON-CONVENTIONAL(IRR) as irrigated. SUMMERFALLOW, CONTINUOUS CROPPING and NO PRACTICE SPECIFIED count as non-irrigated.
  The value is null where sobtpu has no acres. sobtpu acres equal sobcov acres (ratio 1.000), except 2002 (1.008) and 2003 (1.014).
- `lcr_drought` = indem_drought_usd / liability_usd. `drought_usd_per_ac` = indem_drought_usd / insured_acres.
  Both are null when the denominator is 0. All dollar values are nominal USD.

## Outputs
### `data/processed/rma_county_year.parquet`
- Key (fips, year, crop). Columns: fips (5-char str), year (int32), crop, then the 12 contract columns in contract order.
- **70,664 rows**, 667 counties (IA 99, NE 93, KS 105, MO 115, IL 102, SD 66, MN 87), years **2001-2025**.
  By crop: all 16,302; corn 16,010; soybeans 15,361; wheat 13,771; sorghum 9,220.
- A row exists where any of the three files has a record for that county/crop/year, including zero-liability listing rows.
  Absent rows mean RMA has no record, so the value is effectively zero insurance. Rows are not filled in.
- RMA county code 999 ("All Other Counties") is excluded here but included in the state totals. County rows sum to the
  state rows within 0.07% for indemnity.
- Nulls: irrigated_insured_share 2,400; lcr_drought 2,840; drought_usd_per_ac 2,843. All come from zero denominators.

### `data/processed/rma_state_year.parquet`
- Key (state_abbr, year, crop). Columns: state_abbr, state_fips, year, crop, then the same 12 columns. **975 rows** =
  (7 states + `US`) x 25 years x 5 crops, minus the 25 Minnesota sorghum rows. RMA has no grain sorghum (0051) records
  for MN in 2001-2025, so the county table has no MN sorghum rows either. Treat a missing row as "not insured", not as unknown.
- `US` (state_fips "00") sums every state and territory in the files, for every crop including `all`. Ratios are recomputed from the sums.

## Sanity checks (what the files say; snapshot 2026-11-09)
US, all commodities:

| year | total indemnity | drought indemnity | drought share | total premium | subsidy | subsidy / premium |
|---|---|---|---|---|---|---|
| 2012 | $17.45B | $12.99B | 74.4% | $11.12B | $6.98B | 62.8% |
| 2018 | $7.32B | $2.00B | 27.4% | $9.90B | $6.27B | 63.3% |
| 2019 | $10.61B | $0.82B | 7.7% | $10.13B | $6.37B | 62.9% |
| 2020 | $8.71B | $1.65B | 19.0% | $10.07B | $6.32B | 62.8% |
| 2021 | $9.61B | $4.13B | 43.0% | $13.72B | $8.61B | 62.8% |
| 2022 | **$19.43B** | **$7.64B** | 39.3% | $18.39B | $11.63B | 63.2% |
| 2023 | $17.80B | $6.61B | 37.1% | $18.11B | $11.33B | 62.6% |
| 2024 | $15.18B | $3.08B | 20.3% | $15.88B | $9.88B | 62.2% |
| 2025 | $11.61B | $1.56B | 13.4% | $16.83B | $10.59B | 62.9% |

- **2022**: drought $7.64B matches the published $7.6B (EWG). Total indemnity is now **$19.43B**, about 1.7% above the
  published $19.1B, because RMA has kept revising 2022 since that analysis. Cite "$19.4B in current RMA data (EWG: $19.1B)".
- **2001-2022 drought total: $56.60B, 34.9% of all indemnity.** This matches the published $56.6B / ~35%.
- **Subsidy share**: federal subsidy / total premium was 57.8-63.3% in 2001-2025. It ran 58-60% before 2009
  and has stayed at 62-63% since 2011. The commonly quoted "~60-62%" fits, and recent years are slightly above it.
- Iowa 2012: drought indemnity **$1.877B** of $2.016B total (corn $1.631B, soybeans $0.232B).
- Nebraska 2022: drought indemnity **$944.8M** of $1.534B total (corn $606.2M, soybeans $253.8M, sorghum $35.0M, wheat $34.7M).
  For comparison, Nebraska 2012 drought was $1.216B and Iowa 2022 drought was $259.1M.
- Focus county, Plymouth IA (19149), corn: drought $73.1M in 2012 ($324/insured ac, LCR 0.39), $25.7M in 2022
  ($113/ac, LCR 0.105) and $10.8M in 2023.
- Cross-check: colsom total indemnity equals sobcov total indemnity in every year. The largest gap is 2019 ($10.606B vs $10.609B).

## Caveats
- **2025 is provisional.** The 2025 files were last updated on 2026-11-09, about a year after harvest, so most
  row-crop claims are settled. They still change every week as late claims, reversals and specialty-crop and PRF settlements come in.
  2025 national indemnity is currently $11.61B, and the 2025 premium/liability figures are essentially final. Treat 2025 losses
  as near-complete but subject to small upward revision. 2021-2024 files are also still being revised slightly.
  A 2026 crop-year file exists but is not used.
- **PRF in `all`.** Pasture/Rangeland/Forage acres are a large share of insured acres in the western states.
  In 2022 PRF was 20.7% of NE, 22.7% of SD, 13.0% of KS and 45% of US acre-type insured acres (2012: under 4% in each of the 7
  states, 15.5% for the US). PRF acres are cheap rangeland index acres, so `drought_usd_per_ac` for crop=`all` is diluted in
  those states and cannot be compared over time. PRF indemnity is index-based (rainfall index) and is coded entirely as cause
  55 (checked for 2022: all $1.315B of PRF indemnity is cause 55, none is cause 11). So PRF adds to `indem_total_usd` for `all`
  but never to `indem_drought_usd`, even though its losses come from rainfall deficits.
  Use the crop-specific rows (or lcr_drought) for modelling.
- Nominal dollars. Liability rises with crop prices (2011-2014, 2021-2023), so use `lcr_drought` for price-normalized comparisons.
- The cause is the peril that the adjuster recorded for each claim line. RMA's month/stage detail is ignored here (summed over months).
- Revenue Protection indemnities include harvest-price effects, so a drought loss in a high-price year (2012) is larger per bushel.
