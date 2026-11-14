# Facts notes (facts module, 2026-11-14)

Machine-readable values are in `facts.json`. The app must only show facts whose `verification` is not `unverified`, and must show the source with each one.

## How this was checked
I used web search only. The session network refused direct page fetches (iowapublicradio.org, kcci.com and dmww.com were all blocked), so no page was opened in full. I followed the repo's `evidence_priors.json` rule: a number that was not read on the opened original counts as `secondary`. The `source_kind` field shows when the publisher is the primary body (CIWW, USGS, USDA-ARS, USDA-AMS, IDALS, ISU, NCI) and not a news outlet. Quotes come from search extraction, so re-check the exact wording before a quote goes on a slide. To raise these facts to `primary`, open the CIWW FAQ page, the CIWW 193-day release, the NRCS FY26 Iowa booklet and INRS Table 3.

## Confirmed (consistent across 2+ sources, or from the official publisher)
- **About 600,000 people** are served by Central Iowa Water Works (CIWW). CIWW was formed as a regional authority in 2024 and began operating on 1 Jan 2025. It is a cooperative of 12 utilities, not a merger.
- **2025:** the nitrate removal facility ran on **112 days** and was turned off on 8 Aug 2025. It cost **about $2.2M**, made up of **$1.6M O&M + $0.6M capital**. At full capacity it costs **about $16,000/day**.
- **2025 ban:** the first-ever lawn-watering ban started on **12 Jun 2025** and the Stage III ban ended on **7 Aug** (56 days). Homes were released on 22 Jul (40 days). All restrictions ended on 15 Aug. The trigger was river nitrate "near record levels" while all nitrate removal was already at full capacity. Lawn watering is about 40% of summer demand.
- **2026 was worse than 2025:** the facility started on 6 Jan, which was its first January run since 2015. It ran a **record 193 days** (previous record 177 days, set in 2015) and was turned off on 23 Jul. The ban ran from **8 Jun to 20 Jul 2026** (42 days, all customers), and all restrictions ended on 27 Jul. By 8 Jun, the Raccoon had been above 10 mg/L for 136 days and the Des Moines River for 117 days. Q1 2026 O&M was about $660k. The full 2026 cost is due in early 2027.
- **Capacity:** 10 MGD, from 8 ion-exchange vessels (7 active + 1 regenerating).
- **Capital:** the state gave a one-time **$25M** (May 2026) to double nitrate removal capacity within 3 years. The current estimate is **about $40M**, and **ratepayers cover the gap** (KCCI).
- **Records:** the Raccoon record is 24.39 mg/L and the Des Moines River record is 18.62 mg/L, both set in 2013. The 2025 peaks were "near record", not records.
- **Agronomy:** ISU says an average Iowa corn/soy acre loses about **30 lb N/yr**. The range is wide: 15-50 typical, and 0.9-94 at Gilmore City depending on the year. USDA-ARS (Kaspar) found that rye cut nitrate **load by 57%** (concentration by 59%) over **14 years** near Ames. INRS gives rye **31% (SD 29)**, extended rotation **42% (SD 12)**, CRP **85% (SD 9)**, perennial energy crops **72% (SD 23)**, fall-to-spring timing **6% (SD 25)** and a nitrification inhibitor **9% (SD 19)**. The INRS tracking pages give bioreactors 43%, saturated buffers 50% and wetlands 52%.
- **Money:** IDALS 2026 cost-share is **$30/ac first-time, $20/ac returning** (160-ac cap). The Greater Des Moines Watershed adds **$25/ac** on up to 500 ac. The crop insurance discount is **$5/ac**, and only on acres with no other cover crop funding. Custom drilling costs **$19.05/ac** (ISU 2026 survey). Iowa anhydrous was **$1,096/ton in May 2026, about $0.67/lb N**, against about $0.48 in May 2025.
- **Adoption:** about **3.87M acres of cover crops in 2024** (16.7% of corn+soy). The INRS goal is 12.5M acres.
- **USGS:** the Van Meter drainage area of **3,441 mi²** is confirmed. Parameter **99133** means nitrate+nitrite, in situ, mg/L as N.

## Conflicts between sources
- **2025 peak nitrate:** IPR (25 Jun 2025) gives Raccoon 20.55 (8 Jun) and Des Moines 17.15 (12 Jun). IPR (6 Aug 2025) gives Raccoon 19.39 and Des Moines 16.66, and Iowa Capital Dispatch gives Des Moines 16.6. **Compute peaks from our own USGS series.**
- **2025 ban end:** IWLA says "June 12 to July 31, 49 days". That is wrong, and IPR issued a correction that the ban ended in August.
- **2026 residential release:** a CIWW 1 Jul release began a phased easing, while Ankeny and Polk City notices say 20 Jul for all customers. 2026 plant days are given as 193 (CIWW) and 192 (WOI).
- **Cost/day:** CIWW gives $16k at full capacity, Axios gives about $11k, and other reports give $4-16k. Older stories say $10k. Our derived 2025 average is about $14.3k of O&M per operating day.
- **2025 cost:** $2.2M (total) and $1.6M (O&M only) are both correct, but they are different scopes.
- **INRS cover crop:** 31% (2013 table) vs 27% (Iowa Soybean Assn. 2026, citing INRS) vs 28-31% (Farm Bureau). I could not confirm whether the Feb 2025 INRS update revised the table.
- **Wetlands / saturated buffers** differ between INRS tracking editions (wetlands 30 vs 52%, saturated buffers 50 vs 53%).
- **EQIP 340:** a third-party guide says $74.34 regular / $89.20 HU. The NRCS FY26 booklet snippet shows 89.20, which fits the 90%/75% ratio, so this is likely the HU column. I did not see the regular rate in the official booklet.

## Corrections to `docs/concepts/field-to-faucet.md`
1. "15-year Iowa State plots, 57%": the study is **USDA-ARS (Kaspar), 14 years, near Ames**. 57% is the load reduction and 59% the concentration reduction.
2. "Other Iowa sites 22-48%": **not found**. Kaspar's SARE slides give **15-48%**.
3. "$2.2M ... up to about $16k per day": correct, but **$2.2M includes $0.6M capital**. Also, IPR 2026-01-12 says "over 100 days", not 110. The 112 figure comes from KCCI/KJAN and CIWW.
4. The doc leaves out the bigger story: in **2026 the facility ran a record 193 days** and there was a second ban.
5. **Prior art:** NASA funded a University of Iowa nitrate forecasting and early warning system (NFEWS) with Des Moines Water Works in July 2026. Frame Field to Faucet as field-level attribution plus farmer strategies, not "the first nitrate forecast".

## Avoid claiming
- That 2025 or 2026 set a **record concentration**. 2026 set a record for **duration**.
- That nitrate **causes** cancer. Say that studies found associations: NCI's Iowa Women's Health Study found thyroid, ovarian, bladder and kidney cancer associations, and **no** colorectal association in that cohort.
- That the **$1.2B** CIWW capital program is a nitrate cost. It is mostly driven by growth.
- The EQIP 328 rate, the INRS oat and MRTN values, the 6,245 mi² drainage area and the rye seed $/ac. All are marked `unverified` in `facts.json`. EQIP 340 ($74.34) is `secondary` from a third-party guide, so check it in the NRCS booklet before it goes on a slide. FY2025 Iowa rates were not found.
- That the Polk County study says exactly "80%". It reports roughly 70-80% from agriculture, with about 40% from surplus fertilizer.
