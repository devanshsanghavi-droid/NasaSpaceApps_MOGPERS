# Module `evidence`: trial effect priors, citation checks, shock years

## What was built
- `data/evidence_priors.json`: 42 effect priors (E1 18, E2 8, E3 6, E4 6, E5 4), 3 `citation_checks`, a `web_strategy_map`, and a `shock_years` block.
- `pipeline/evidence_build.py`: holds the hand-curated priors (each with source, URL/DOI and verification level), attaches the web mapping and unit fields, enforces consistency asserts, and writes the JSON.
- `pipeline/evidence_usdm.py`: fetches US Drought Monitor county statistics for the **14 tile counties listed in `data/counties.geojson`** (2016-2024) into `data/raw/usdm/` and summarizes them. `shock_years` uses the 8 core counties (Story, Boone, Polk, Marshall, Hamilton, Hardin, Jasper, Dallas).

Re-run (cached, about 2 s, deterministic apart from `generated_at`):
```
.venv/bin/python pipeline/evidence_usdm.py
.venv/bin/python pipeline/evidence_build.py
```

## Strategy IDs: evidence E1..E5 are NOT web S0..S3
Evidence IDs were renamed from S1..S5 to **E1..E5** so they cannot be joined to web cards by accident. Join on `web_strategy_id` (per prior) or the top-level `web_strategy_map`, **never on `strategy_id`**.

| Evidence ID | Practice | `web_strategy_id` | Note |
|---|---|---|---|
| E1 | cereal rye cover crop | S1 | Web S1 is rye **before soybean** only. E1 priors with `variant == "before_corn"` carry `variant_mismatch: true` (4 records: PFI corn counts, Pantoja corn, Marcillo, Deines corn). Variant `both` / `before_soybean_and_corn` records are general rye effects (nitrate, erosion, N2O, SOC, infiltration). |
| E2 | no-till / reduced tillage | S2 | |
| E3 | prairie strips | **null** | No web card. Do not attach these priors to any card. |
| E4 | extended rotation (C-S-oat/clover) | S3 | The web S3 "Diversify" branch for corn-soy fields. |
| E5 | corn-soy vs continuous corn | S3 | The web S3 "Diversify" branch for continuous-corn fields. |

## JSON layout
`{generated_at, module, description, web_strategy_map, strategies{E1..E5 (+web_card)}, verification_levels, priors[...], citation_checks[...], shock_years{method, source, events[...], assessment_for_hindcast, by_year_all}}`

Each prior has these fields:
- `prior_id, strategy_id (E1..E5), variant, outcome`
- `web_strategy_id` (S1/S2/S3/null), `variant_mismatch` (bool), `web_variant_note`
- `web_key`: the `effects.json` outcome it can inform (yield_pct / erosion_t_ac / drought_loss_pct / n2o_pct / nitrate_pct / null)
- `web_unit_compatible`: true means the value is already in the web_key's unit (% change of treatment vs control). false means apply `conversion` first. null means web_key is null.
- `conversion`: a text recipe, e.g. "relative change: erosion_t_ac_treated = phase2 baseline erosion_t_ac x (1 + mean/100)" or "t/ha/yr x 0.4461 = short t/ac/yr".
- `prior_kind`: `numeric` | `counts` | `range` | `qualitative`. **Only `numeric` priors have a usable `effect.mean`.** All non-numeric records have `mean = null` and `use_as_prior = false` (enforced by assert).
- `effect{mean, unit, ...}`. A published number that was converted is kept under `effect.reported`. Ranges that are not CIs go in `effect.range`.
- `uncertainty{se, ci95, note}`: `ci95` holds only real or SE-derived 95% CIs, stored as [lower, upper].
- `n, design, region, source, url, doi, summary, applicability, verification` (full_text | abstract | secondary), `derived` (+`derivation` formula), `use_as_prior`.

**Units/direction:** `mean` is the % change of treatment vs control (negative = reduction) unless `unit` says otherwise. For E5 the treatment is the corn-soy rotation and the control is continuous corn. Every E5 yield prior is a **rotation benefit as % of CC yield** (benefit = 1/(1 - penalty) - 1).

## Exact counts (from the current JSON)
- 42 priors: **30 `use_as_prior = true`, 12 false**.
- `prior_kind`: 37 numeric, 2 counts (PFI soy/corn), 2 qualitative (Basche 2014 N2O LRR, He 2025 N2O n.s.), 1 range (Bowles 2020).
- DOIs: 40 of 42 priors have one (the 2 PFI records have none). There are **25 unique DOIs, and all 25 resolved on Crossref** (2026-11-14) with matching title, volume and pages.
- Usable numeric priors by web_key (use_as_prior = true): yield_pct 10, erosion_t_ac 5 (all need conversion), nitrate_pct 4, n2o_pct 1, **drought_loss_pct 0**.

## drought_loss_pct has NO numeric trial prior
The only drought record is Bowles 2020 (E4), which gives a 14-90% range across sites with no central value and no Iowa site, so it is `use_as_prior = false`. Won 2024 (prevented planting) measures excess-wet losses in national USD; its web_key is now null. **Phase 2 must estimate drought_loss_pct from the tile data or badge it "thin".**

## erosion_t_ac priors all need conversion
None of them is in short t/ac:
- Relative % changes, applied as baseline erosion_t_ac x (1 + mean/100): Kaspar 2001 (rye, -54% interrill, on top of no-till residue), Mhazo 2016 (-60%), Prasad 2023 ("up to" -86%, an upper bound), Schulte 2017 strips (-95%, no web card).
- Lindstrom 1992 is an absolute magnitude, 30 t/ha/yr off convex knolls under moldboard plowing. It converts as t/ha/yr x 0.4461 = 13.4 short t/ac/yr and scales the tillage-erosion term.
- Thaler 2021 (35% of Corn Belt area has lost its A horizon) is a status statistic, not a treatment effect. Its web_key is null and it is context only.

## Priors table (central values)
| ID | Outcome | Effect | Uncertainty | Design / n | Source |
|---|---|---|---|---|---|
| E1 rye -> soy | yield | counts: 20/29 trials no effect, 8 gains (counts, not a prior) | - | PFI strip trials | PFI/ILF (Gailans 2019) |
| E1 rye -> soy | yield | +0.2% (59.1 vs 59.0 bu/ac), n.s. | - | RCT plots, 4 Iowa sites, 2009-2013 | Pantoja 2015 SSSAJ + ISU report (full text) |
| E1 rye -> soy | yield (contrast) | -3.5% | - | observational | Deines 2023 |
| E1 rye -> corn [mismatch] | yield | **-4.6%** at EONR (179 vs 188 bu/ac, 2009-2013); SSSAJ 2009-2011 subset -6% | - | RCT plots | Pantoja 2015 + ISU report (full text) |
| E1 rye -> corn [mismatch] | yield | 0 (grass covers) | n.s. | meta-analysis, 65 studies | Marcillo & Miguez 2017 |
| E1 | US main-crop yield | -3.1% | - | meta-analysis | He 2025 |
| E1 | interrill erosion | -54% (rill -90%) | 2 of 3 yr sig. | rainfall simulation | Kaspar 2001 (doi 10.1080/00224561.2001.12457370) |
| E1 | nitrate leaching | -56% | CI -66 to -43 | meta-analysis | Thapa 2018 |
| E1 | tile nitrate load | -61% | sig. all 4 yr | drained plots | Kaspar 2007 |
| E1 | tile nitrate conc. | -48% | - | drained plots | Kaspar 2012 |
| E1 | N2O total | -12.7% | n.s. (P=0.155) | 10-yr field exp. | Parkin 2016 |
| E1 | SOC | +4.0% | CI 1.5-6.7 | meta-analysis | He 2025 |
| E1 | infiltration | +34.8% | SE 7.7, CI 19.7-49.9 (derived) | meta-analysis | Basche & DeLonge 2019 |
| E2 no-till | maize yield | -7.6% | - | meta-analysis | Pittelkow 2015 FCR |
| E2 | corn yield, Ames C-S | -14% vs chisel | NT sig. lower | long-term RCT | Al-Kaisi 2015 |
| E2 | soil loss | -60% | - | meta-analysis | Mhazo 2016 |
| E2 | sediment | up to -86% (runoff +70-84%) | - | meta-analysis | Prasad 2023 J ASABE 66(6):1341-1354 |
| E2 | tillage erosion | 30 t/ha/yr (13.4 short t/ac/yr) off knolls under moldboard | simulated | model | Lindstrom 1992 |
| E2 | infiltration | +5.7% n.s. | SE 9.7, CI -13.3 to 24.7 (derived) | meta-analysis | Basche & DeLonge 2019 |
| E2 | SOC | +0.27 t C/ha/yr | CI 0.00-0.56 | meta-analysis | Ogle 2019 |
| E3 strips | sediment | -95% | CI -98 to -82 | randomized catchments, Jasper Co. | Schulte 2017 |
| E3 | total P | -77% | CI -93 to -29 | same | Schulte 2017 |
| E3 | total N surface (web_key null; not nitrate) | -70% | CI -92 to +11 | same | Schulte 2017 |
| E3 | groundwater NO3-N (nitrate_pct) | -72% | CI -92 to 0 | same | Schulte 2017 |
| E3 | runoff | -37% | CI -57 to -9 | same | Schulte 2017 |
| E3 | yield, cropped area | 0 | n.s. | same | Schulte 2017 |
| E4 3-4 yr rotation | corn / soy yield | +4% / +9% | p=0.03 / 0.01 | RCT, Marsden | Davis 2012 |
| E4 | N fertilizer | -83% (derived) | - | same | Davis 2012 |
| E4 | herbicide | **-88%** (reported); 6-10x spread in effect.range [-90, -83.3], not a CI | - | same | Davis 2012 |
| E4 | drought-year loss | range 14-90% (range, use_as_prior=false) | - | 11 NA sites | Bowles 2020 |
| E4 | corn yield (contrast) | -3.4% | sig. | observational | Kluger 2025 |
| E5 rotation vs CC | corn yield | **+1.03 t/ha** (cool 1.19, hot 0.85); soy +0.21 (cool 0.16, hot 0.24). web_key null until converted to % | - | trial + satellite hybrid | Kluger 2022 ERL 17(4):044066 |
| E5 | corn yield | **+18.5%** at Ames (10.49/8.85-1); range +12.4% to +38.9% across 7 sites (from 11-28% penalty) | site range, not CI | long-term RCT | Al-Kaisi 2015 |
| E5 | corn yield (contrast) | +4.5% (from reported 4.3% CC penalty) | - | observational | Seifert 2017 |
| E5 | corn yield (contrast) | +2.5% of mean US corn yield | sig. | observational | Kluger 2025 |

Three key trials sit **inside the tile**: STRIPS at Neal Smith NWR (Jasper Co.), Marsden Farm (Boone), and the Al-Kaisi Ames site. Kaspar, Parkin and Pantoja are also central Iowa.

## Changes in this revision (verifier fixes)
- Renamed the evidence IDs to E1..E5. Added `web_strategy_map`, plus per-prior `web_strategy_id`, `variant_mismatch` and `web_variant_note`.
- Added `prior_kind`. PFI counts, Basche 2014, He 2025 N2O and Bowles 2020 are now `use_as_prior = false`. Al-Kaisi E5 now has a derived mean of +18.5%.
- Re-expressed every E5 yield prior as rotation-vs-CC % change. The published values are kept in `effect.reported`. Kluger 2022 (t/ha) has web_key null, `web_key_after_conversion: "yield_pct"` and a conversion recipe.
- Added `web_unit_compatible` and `conversion` to every prior. Set web_key to null for Won 2024, Thaler 2021 and Schulte total N.
- Davis herbicide: mean is now -88% (reported directly, read in the PLoS full text). The 6-10x spread moved to `effect.range`, and ci95 is null. The Basche infiltration CIs are flagged `derived` ("ci95 = mean +/- 1.96*SE").
- Kluger 2022 now uses the journal abstract values (checked against Crossref), and its URL points to the DOI.
- Pantoja corn now has its DOI. The ISU farm report full text was read (soy 59.1 vs 59.0; corn 179 vs 188, -4.6%), so both Pantoja records are now `full_text`. The corn mean changed from -6% (SSSAJ abstract, 2009-2011) to -4.6% (2009-2013), and -6% is kept in `effect.reported_sssaj_2015_pct`. Added the Kaspar 2001 DOI. Added the Prasad pages.
- USDM: the county list is now built from `data/counties.geojson` (14 fips). Tama and Poweshiek are dropped, so no out-of-tile data reaches the CSVs. The old cached JSONs `data/raw/usdm/usdm_19171_*.json` and `usdm_19157_*.json` are still on disk but unused. `usdm_core_by_year.csv` now uses the same monthly-mean aggregation as the JSON, and the build asserts they agree.

## Citation checks
1. **PCCP 2021, "12.2 million acres": partly.** About 12.2 million net acres received the 2021 premium reduction (FCIC/RMA final rule, doc 2022-02965). AFT puts the cost at $59.4M. No source was found for a "5M forecast"; drop it.
2. **Kluger, Di Tommaso & Lobell 2025: verified.** Environ. Res. Lett. 20(11):114037, doi 10.1088/1748-9326/ae0f45. The 4.5% is the median net rotation benefit across 36 precrop x crop x country combinations in 4 countries. US corn is +2.5%.
3. **Won et al. 2024 AJAE: partly.** The estimate is for a one-percentage-point adoption increase using 2019 data: loss ratio 4.47% -> 4.43%, ~3.9M acres, ~$38.69M lower indemnities. "$40M per 1%" is press-release wording. The full text returned HTTP 403, so re-check before printing.

## Shock years (USDM, 8 core counties, May-Sep)
**Canonical method:** the `shock_years` block in the JSON. For each month, take the mean over the core-county weekly rows, round it to 0.1, then average the May-Sep monthly means. `data/raw/usdm/usdm_core_by_year.csv` uses the identical method (its other columns are labelled diagnostics).

| Year | D1+ | D2+ | Note |
|---|---|---|---|
| 2016-2019 | 0-30 | 0 | no growing-season drought (2017 D1 ~30%) |
| 2020 | 42.8 | 22.5 | **Derecho 10 Aug 2020** (Marshalltown 99 mph; NCEI $11.0B) plus Jul-Oct drought |
| 2021 | 89.9 | 38.7 | **most severe in-season drought of the panel** (falls in the training years) |
| 2022 | 13.2 | 2.8 | drought starts in Aug; late-season |
| 2023 | 34.6 | 10.6 | D1 13-34% Jun-Aug, then 97% in Sep |
| 2024 | 5.8 | 1.6 | |

**Flag for phase2/hindcast:** in this tile the 2022-2023 drought was late-season and moderate. 2021 was the bigger in-season drought and sits in the training window. Define `drought_flag` from weather data, not by calendar year.

USDM raw: `usdm_tile_weekly.csv` has 14 counties x 471 weeks, no duplicates, and D0>=D1>=D2>=D3>=D4 everywhere. `usdm_tile_summary.csv` has 126 rows (14 x 9 years).

## Caveats
- Most priors have no SE or CI in the source (`se`/`ci95` = null). Do not invent widths downstream.
- `verification: secondary` records (PFI counts, Kaspar 2001 erosion %, Lindstrom 30 t/ha/yr, Marcillo effect sizes, Won numbers) were not read in the original paper.
- Pittelkow 2015 Nature's overall "-5.7%" could not be confirmed. The FCR companion maize value (-7.6%) is used.
- Bowles 2020 is an upper bound: it compares the most diverse rotation against the simplest and includes no Iowa site.
- Observational studies (Deines, Seifert, Kluger 2025) carry `use_as_prior = false`. They are net-effect contrasts.
- Prasad's -86% is an "up to" value. Prefer Mhazo's -60% as the central no-till erosion prior.
