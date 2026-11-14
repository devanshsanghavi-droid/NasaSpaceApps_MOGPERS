# Drought Bill: fact-check of headline impact claims

Checked 2026-11-14.

**How these were checked.** This session's network allowed direct reads from only two of the needed hosts: `www.ers.usda.gov` (USDA Economic Research Service) and `www.fb.org` (American Farm Bureau). The pages were fetched with curl and the ERS Excel data was downloaded and summed. These hosts were blocked, so their pages could not be opened: ewg.org, rma.usda.gov, gao.gov, cbo.gov, cell.com, doi.org, iopscience, arxiv, sare.org, the extension sites, ResearchGate and PMC.

Where a source could not be opened, the figure is still marked **UNVERIFIED**, even when several web-search snippets agree on it. The note says what the snippets show and which USDA number (read directly) can stand in for it.

**Verdict key.** VERIFIED = read in the source. PARTIAL = the number or its context differs, and the correct number is given. UNVERIFIED = the source could not be opened.

## Summary table

| # | Claim (as pitched) | Best source | Figure found | Verdict | Use instead / note |
|---|---|---|---|---|---|
| 1 | 2022: drought was the costliest cause of loss at $7.6B (EWG / RMA) | EWG, "Crop insurance pays farmers billions of dollars for weather-related losses closely linked to the climate crisis" (Nov 2023). Could not be opened. Cross-checked against ERS cause-of-loss data (read). | EWG $7.6B (search snippets). ERS "drought and high temperature" 2022 = **$10.79B** of $19.43B total (55.5%). | UNVERIFIED (EWG). The USDA data supports "costliest cause". | Say "$7.6B (EWG, 'drought' cause code)" or "$10.8B (USDA ERS, drought + heat)". Don't mix the two. |
| 2 | 2022 indemnities hit a record $19.1B | EWG news release, Sep 2023 ("record $19.13B"). Could not be opened. ERS FCIP indemnities by cause (read). | EWG $19.13B (snippets). ERS total 2022 = **$19.43B** (RMA data as of 25 Aug 2024). It is the highest year in the ERS 1990–2024 series. | PARTIAL | "A record ~$19.4B (USDA ERS/RMA, 2024 data)". $19.1B is EWG's earlier data pull. |
| 3 | 2001–2022: drought = $56.6B, ~35% of all payouts | EWG (same Nov 2023 report). Could not be opened. | EWG $56.6B / 35% (snippets). ERS drought + heat 2001–2022 = **$70.5B of $162.0B (43.5%)**. ERS text: drought/heat averaged **41%** of indemnities since 2000. | UNVERIFIED (EWG). Context differs from USDA's category. | Quote EWG with attribution, or use ERS "41% since 2000" (read). |
| 4 | 2023 crop + rangeland losses from major disasters > $21.9B (AFBF) | AFBF Market Intel, D. Munch, 29 Feb 2024 | "over **$21.94 billion**" | VERIFIED | Of that, ~$12B was covered by RMA and ~$10B was not. Drought, heat and wildfire accounted for $16.59B. |
| 5a | Taxpayers pay ~60% (e.g. 62%) of premiums | ERS Charts of Note, 23 Jan 2015 (read). ERS chart, 8 Mar 2014 (read). GAO-24-106086 (Nov 2023) could not be opened. | ERS: "an average of **62 percent** of total premiums ... in 2013". ERS: "roughly **60 percent**". GAO / press for 2022: ~62% (snippets; one outlet said 65%). | VERIFIED for 2013 (62%). Recent figure UNVERIFIED. | "~62%" is defensible. ERS cost data ÷ implied premium gives ≈63–66% for 2021–24 (rough). |
| 5b | Total annual federal cost of the program | ERS "Crop Insurance at a Glance", updated 23 Sep 2025, plus its `fcip_costs.xlsx` (read) | 2024: **$15.08B** (premium subsidy $10.43B + delivery $2.34B + underwriting gains $2.31B). 2022: **$16.92B**. 2015–24 average: **$11.7B/yr**. GAO: 2022 = $17.3B (snippet). | VERIFIED (ERS) | "About $15B in 2024 (USDA ERS)". |
| 6 | Bowles et al. 2020: diverse rotations cut maize drought-year losses by 14–90% | Bowles et al., *One Earth* 2(3):284–293, DOI 10.1016/j.oneear.2020.02.007. cell.com and the PDF mirrors were blocked. | 28.1% average maize yield gain (22.6% in favourable years). Drought-year losses reduced by **14.0%–89.9%**. 347 site-years, 11 experiments. | UNVERIFIED (not opened). All numbers are consistent across several snippets. | One snippet from an OSU-hosted PDF shows "88.9%" in the results text. Check the final PDF before printing "89.9%". |
| 7 | Kluger et al.: rotation benefit shrinks in hot/dry years | Kluger, Owen & Lobell 2022, *Environ. Res. Lett.* 17:044066, DOI 10.1088/1748-9326/ac6083. Blocked. | Corn rotation benefit **0.84 t/ha** (hottest temperature quintile) vs **1.02** (all) vs **1.18** (coolest), per arXiv v1. A DOAJ snippet gives 0.85 / 1.03 / 1.19. The benefit is about 29% smaller in the hottest quintile than the coolest. | UNVERIFIED. Context: the split is by **temperature**, not drought. | Say "smaller in hotter years". Don't say "drought" unless the paper says so. |
| 8 | 2012 drought indemnities ≈ $17.3B (record at the time) | ERS `fcip_indemnities_by_cause_of_loss.xlsx` (read). USDA April 2013 press figure (snippet). | ERS 2012 total = **$17.45B**. Drought + heat = **$14.56B (83.4%)**. USDA reported $16.99B in Apr 2013. The previous record was $10.8B (2011). | PARTIAL | "~$17.4B, 83% from drought & heat (USDA ERS)". |
| 9 | Cover crops: 2012 drought yield bump of 9.6% corn / 11.6% soybean (SARE/CTIC); soil-water risk | SARE/CTIC 2012–13 National Cover Crop Survey (sare.org blocked; MSU Extension and others in snippets). Nielsen et al. 2016 *Agron. J.* (snippets). | Corn **+9.6%**, soybean **+11.6%**. Worst-drought areas: +11.0% / +14.3%. >750 farmers, self-reported. Great Plains: wheat after cover crops ~10% lower than after fallow, with bigger losses in dry years. 5.94 bu/ac lost per inch of unreplaced water. | UNVERIFIED (numbers consistent across snippets). | Label as a **farmer survey, not a controlled trial**. Pair it with the dryland soil-water caveat. |
| 10 | Sorghum is more drought tolerant / uses less water than corn | K-State Agricultural Experiment Station reports. UNL CropWatch (Rees 2013). Both from snippets. | UNL 2009–11 rainfed trial: sorghum used ">2 in. less ET than corn or soybean" and had higher WUE. K-State: advantage in environments under 80 bu/a. | UNVERIFIED (snippets) | Frame it as "in dryland / low-yield environments". Corn has the higher yield ceiling. |

## Notes per claim

### 1. 2022 drought = $7.6B, costliest cause (EWG)
- **Source (not opened):** EWG, *Crop insurance pays farmers billions of dollars for weather-related losses closely linked to the climate crisis*, Nov 2023. https://www.ewg.org/research/crop-insurance-pays-farmers-billions-dollars-weather-related-losses-closely-linked-climate. The same figure appears in coverage by Investigate Midwest (2 Nov 2023) and Insurance Journal (15 Nov 2023).
- **What search snippets say:** drought payouts were "$7.6 billion" in 2022, a "690% increase" from $965.5 million in 2001.
- **USDA cross-check (read):** ERS file `fcip_indemnities_by_cause_of_loss.xlsx` (RMA Summary of Business cause of loss, as of 25 Aug 2024). The 2022 "Drought and high temperature" group = $10.79B, the largest peril group (excess moisture $2.29B, other $4.97B). ERS's group also includes heat, hot wind, fire and irrigation failure. EWG's $7.6B is presumably the narrower "drought" cause code. "Costliest cause in 2022" therefore holds under either definition. https://www.ers.usda.gov/topics/farm-practices-management/risk-management/crop-insurance-at-a-glance

### 2. 2022 record indemnities $19.1B
- **Source (not opened):** EWG news release, Sep 2023, "EWG: Farmers received record $19.13B in crop insurance indemnities in 2022." https://www.ewg.org/news-insights/news-release/2023/09/ewg-farmers-received-record-1913b-crop-insurance-indemnities
- **Read (ERS data):** the 2022 sum across all peril groups = **$19.43B**. That is the series maximum for 1990–2024 (2023 $17.77B; 2012 $17.45B).
- Indemnity totals keep moving as late claims settle. A search snippet cites RMA's 2023 accomplishments page at $19.8B for crop year 2022 (not opened).
- **Recommendation:** "record ~$19.4 billion (USDA ERS, from RMA data)".

### 3. 2001–2022 drought $56.6B, 35%
- **Source (not opened):** the same EWG Nov 2023 report. Snippet: drought "was the costliest cause of loss ... $56.6 billion, or 35 percent of total payouts". Corn accounted for ~$22.6B of drought indemnities.
- **Read (ERS):** "drought and high temperature were a leading cause of indemnified losses in 14 of the 25 years since 2000, averaging 41 percent of total indemnity payments over the same period." Summing the ERS file for 2001–2022 gives $70.5B of $162.0B (43.5%).
- The gap comes from category definitions (drought only vs drought + heat + related causes) and data vintage.

### 4. AFBF 2023 losses > $21.9B — VERIFIED
- **Source (read):** Daniel Munch, AFBF Market Intel, "Major Disasters and Severe Weather Caused Over $21 Billion in Crop Losses in 2023," 29 Feb 2024. https://www.fb.org/market-intel/major-disasters-and-severe-weather-caused-over-21-billion-in-crop-losses-in-2023
- Quote: "The assessment puts total crop and rangeland losses from major 2023 disasters at over $21.94 billion, or 23.6% of NOAA's total economic impact figure. Of that figure, nearly $12 billion in losses were covered by existing Risk Management Agency (RMA) programs as of February 2024."
- Quote: "Drought, excessive heat and wildfires alone accounted for over $16.59 billion in total crop losses".
- **Caveats in the source:** the estimate excludes infrastructure, livestock, complete horticulture and timber losses, and should be treated as "a minimum baseline". The 2022 and 2023 methods differ, so the two years "are not directly comparable".

### 5. Federal share of premiums and total program cost
- **Read:** ERS Charts of Note, "Federal Crop Insurance costs vary with enrollment, subsidy rates, and crop losses" (E. O'Donoghue, 23 Jan 2015). https://www.ers.usda.gov/data-products/charts-of-note/77947
  - Quote: "Under the current premium subsidy structure, an average of 62 percent of total premiums is paid by the Federal Government on behalf of insured producers in 2013."
- **Read:** ERS chart (R. Claassen, 8 Mar 2014). https://www.ers.usda.gov/data-products/chart-gallery/59302
  - Quote: "On average, the Federal Government pays roughly 60 percent of crop insurance premiums".
- **Not opened:** GAO-24-106086, *Crop Insurance: Update on Opportunities to Reduce Program Costs* (Nov 2023; released 4 Dec 2023). https://www.gao.gov/products/gao-24-106086
  - GAO summary snippet: "In 2022, federal costs were $17.3 billion—with about $12 billion subsidizing premiums".
  - Press coverage of the report says government pays "on average about 62%" of premiums. The Star Tribune said 65%.
- **Read (cost):** ERS Crop Insurance at a Glance (updated 23 Sep 2025).
  - Quote: "Premium subsidies totaled $10.4 billion for 2024. ... In 2024, the cost of the program delivery (administrative costs) was $2.34 billion and $2.31 billion was paid as underwriting gains to AIPs."
  - Quote: "Total FCIP outlays ... for 2015–24 averaged $11.7 billion".
  - From `fcip_costs.xlsx`, total outlays: 2022 $16.92B, 2023 $15.51B, 2024 $15.08B.
- **Rough derived check (my calculation; data vintages mixed):** implied total premium = ERS indemnities ÷ ERS loss ratio. The subsidy share comes out at ≈64% in 2022 and ≈63% in 2024.
- **CBO:** not opened. A Cato post citing CBO gives 2026 premiums of $20.4B, of which government pays $12.6B (~62%).
- **Recommendation:** "taxpayers cover about 62% of premiums; the program cost ~$15B in 2024 (USDA ERS)".

### 6. Bowles et al. 2020, One Earth
- **Citation:** Bowles, T.M., Mooshammer, M., Socolar, Y., et al. (2020). Long-Term Evidence Shows that Crop-Rotation Diversification Increases Agricultural Resilience to Adverse Growing Conditions in North America. *One Earth* 2(3): 284–293. https://doi.org/10.1016/j.oneear.2020.02.007
- **Not opened:** cell.com, doi.org and all PDF mirrors (lter.kbs.msu.edu, scholars.unh.edu, food.berkeley.edu, par.nsf.gov) were blocked.
- **Abstract wording (snippet, MSU LTER citation page):** "More diverse crop rotations increased maize yields over time and across all growing conditions (28.1% on average), including in favorable weather conditions (22.6%)." Your recollection of 28.1% matches.
- **Drought (highlight snippet):** "yield losses were reduced by 14.0%–89.9% in drought years". Drought years were "putative drought years identified with crop-insurance" indemnity data. Maize yield was higher with diversity at 9 of 11 sites.
- **Flag:** one snippet of an OSU-hosted copy reads "14.0% and 88.9%" in the results text. Confirm 89.9% against the publisher PDF.
- **What "diversity" meant:** 11 long-term North American experiments (US and Canada; 347 site-years). Simple rotations (maize monoculture or two-crop maize–soybean) were compared with diverse rotations of 3–5 crops. The added crops included small grains (oats, winter wheat, spring barley), forage legumes (alfalfa, red clover), peas and cereal rye cover crops. Yield was modelled per unit of a rotation-diversity index, so the effect scales with how much diversity is added. The exact index formula could not be confirmed without the methods section.

### 7. Kluger, Owen & Lobell 2022, ERL
- **Citation:** Kluger, D.M., Owen, A.B., Lobell, D.B. (2022). Combining randomized field experiments with observational satellite data to assess the benefits of crop rotations on yields. *Environ. Res. Lett.* 17: 044066. https://doi.org/10.1088/1748-9326/ac6083 (preprint arXiv:2112.13700). Not opened.
- **Abstract numbers (snippet of arXiv v1):** the corn rotation benefit was "0.84 t/ha (0.23 t/ha) on average for the top quintile of temperatures, 1.02 t/ha (0.20 t/ha) on average for the whole dataset, and 1.18 t/ha (0.15 t/ha) on average for the bottom quintile of temperatures." A DOAJ snippet of the published version gives 0.85 / 1.03 / 1.19.
- The hybrid estimator beat experiments-only by 13% RMSE and observational-only by 26%.
- An IOP snippet says the reduced benefit under hot, dry conditions could not have been detected from the experiments alone, because only one experimental site-year was that hot and dry.
- **Context:** the headline split is by growing-season **temperature** quintile. The benefit shrinks by about 0.34 t/ha (≈29%) from the coolest to the hottest quintile, and stays positive. Follow-up work (e.g. *Global Change Biology* 2024, doi 10.1111/gcb.17556) links warmer non-growing seasons to smaller corn rotation benefits.
- **Implication for the pitch:** rotation's benefit to corn appears to *shrink* in hot years. That cuts against a simple "rotation = drought insurance" story, so present Bowles (diverse rotations) and Kluger (corn–soy rotation, heat) together and honestly.

### 8. 2012 drought indemnities
- **Read (ERS data):** 2012 total indemnities = **$17.45B**. "Drought and high temperature" = **$14.56B (83.4%)**. The 2012 loss ratio was 1.57. ERS Charts of Note (read): "In 2012, the widespread U.S. drought led to a large increase in the government share of indemnities due to crop losses."
- **Snippets (not opened):** in April 2013 USDA reported $16.99B. Corn accounted for $11.7B (68%) of claims. The prior record was $10.8B (2011).
- **Verdict:** ~$17.3B is within the range of revised figures, but the current USDA number is **$17.4B**, with ~83% due to drought and heat. 2012 was the record until 2022.

### 9. Cover crops and drought
- **SARE/CTIC survey (not opened; MSU Extension, Strip-Till Farmer and others in snippets):** "corn planted after cover crops had a 9.6% increase in yield compared to side-by-side fields with no cover crops. Likewise, soybean yields were improved 11.6% following cover crops." In the hardest-hit drought areas the figures were +11.0% corn and +14.3% soybean. More than 750 farmers responded, mainly in the Upper Mississippi basin, in winter 2012–13. These are **self-reported, non-randomized** comparisons. https://www.canr.msu.edu/news/survey_shows_improved_corn_and_soybean_yields_when_cover_crops_were_seeded
- **Controlled evidence (snippets):** Marcillo & Miguez 2017 meta-analysis (*J. Soil Water Conserv.*) found a "neutral (for grasses) to positive" effect of winter cover crops on corn yield. Grass covers such as cereal rye showed no average yield gain. No meta-analysis isolating drought years was found.
- **Soil-water risk (snippets):** Nielsen et al. 2016, *Agron. J.* (Central Great Plains, Akron CO). Wheat after cover crops yielded ~10% less than after fallow, with larger reductions in drier conditions. UNL CropWatch summary: "subsequent wheat yield was reduced by 5.94 bushels per acre for every inch of water used by the cover crop that was not replenished". Obour, Holman et al. (K-State, 2019) found cover crops lowered soil water at wheat planting in 2 of 3 years. A semi-arid rye study found that late termination (after corn planting) cut corn yield in a dry year (324 mm) but not a wet one.
- **Pitch framing:** cover-crop drought benefits are survey-based and region-dependent. In the western Plains, cover crops can deplete spring soil moisture.

### 10. Sorghum vs corn
- **Snippets (K-State AES reports via newprairiepress.org; UNL CropWatch "SorghumU" Rees 2013):**
  - K-State: "sorghum presents a yield advantage over corn due to having a greater tolerance to drought".
  - K-State: in environments yielding under 80 bu/a, "sorghum has a yield advantage over corn because of its lower input costs and superior WUE and heat tolerance. Sorghum's yield potential is not as high as corn's."
  - UNL 2009–2011 rainfed trial: sorghum "had a higher crop water use efficiency and used over 2" less ET than corn or soybean".
- **Framing:** sorghum is a drought-hedge crop for dryland and low-yield environments. Corn wins where water is ample.

## Sources read directly
- ERS, Crop Insurance at a Glance (updated 9/23/2025), plus `fcip_indemnities_by_cause_of_loss.xlsx`, `fcip_costs.xlsx` and `fcip_loss_ratio.xlsx`: https://www.ers.usda.gov/topics/farm-practices-management/risk-management/crop-insurance-at-a-glance
- ERS Charts of Note 77947 (2015-01-23): https://www.ers.usda.gov/data-products/charts-of-note/77947
- ERS Chart 59302 (2014-03-08): https://www.ers.usda.gov/data-products/chart-gallery/59302
- AFBF Market Intel (2024-02-29): https://www.fb.org/market-intel/major-disasters-and-severe-weather-caused-over-21-billion-in-crop-losses-in-2023

To turn the UNVERIFIED rows into VERIFIED, allow these hosts and re-run the checks: ewg.org, gao.gov, cell.com (or doi.org), iopscience.iop.org (or arxiv.org), sare.org, cropwatch.unl.edu and newprairiepress.org.
