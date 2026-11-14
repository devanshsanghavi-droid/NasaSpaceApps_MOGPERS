# Facts notes (facts module, verified 2026-11-14)

Machine-readable values are in `facts.json` (64 facts). The app must only show facts whose `verification` is not `unverified`, and must show the source with each one. Every fact has `checked_at: "2026-11-14"`.

## How this was checked
The first pass used web-search snippets only. In the verification pass, I fetched and read the original pages on ciww.gov, kcci.com, iowapublicradio.org, nutrientstrategy.iastate.edu (INRS PDFs), ars.usda.gov, iowaagriculture.gov, extension.iastate.edu (AgDM PDFs) and waterservices.usgs.gov (NWIS site, IV and DV services).

`verification` levels:
- **primary**: I read the number on the fetched page. `quote` is copied from that page and is 40 words or fewer. Quotes from PDF tables are flattened rows.
- **derived**: our own arithmetic from primary dates. These are the ban day counts.
- **secondary**: the original could not be opened.
- `extra_quotes`: supporting quotes, each with its URL.
- `inrs_2024_update`: the INRS Science Team's March 2024 revised efficiencies.

Two hosts were allowed but dropped every connection (HTTP/2 INTERNAL_ERROR / empty reply): **nrcs.usda.gov** (EQIP booklet) and **mymarketnews.ams.usda.gov** (fertilizer report). Other hosts were blocked by the proxy: stories.cals/crops.extension/news.iastate.edu, sare.org, dceg.cancer.gov, PMC, kdsm17, axios and yahoo.

**Result:** 52 primary, 2 derived, 9 secondary, 1 unverified.

## Now primary (key numbers)
- **People served:** "more than 600,000" (CIWW). IPR describes this as "one in five Iowans".
- **Facility:** 10 MGD from 8 vessels, with at least 3 and up to 7 running and 1 regenerating (CIWW FAQ). Normal demand is 70-80 MGD, so the facility treats only a fraction of it and its water is blended (IPR).
- **2025 run:** 112 days. The facility ran 10-18 Apr and again 28 Apr - 8 Aug (KCCI; CIWW's "102 days through 29 Jul" agrees).
- **2025 cost:** $2.2M = $1.6M O&M + $0.6M capital. Full capacity costs about $16,000/day. Q1 2026 O&M was about $660k (CIWW FAQ). Our derived average is about $14.3k O&M per operating day.
- **2026 run:** a record 193 days, **6 Jan - 2 Mar and 9 Mar - 23 Jul** (CIWW; KCCI). The previous record was 177 days in 2015.
- **Bans:**
  - 2025: started 12 Jun. Homes were released 22 Jul, businesses 30 Jul, and governments and schools 7 Aug (end of Stage III). All restrictions ended 15 Aug. Restrictions had begun 30 May with a voluntary 25% cut.
  - 2026: started 8 Jun. Homes were released **1 Jul** (23 days) and businesses and governments 20 Jul (42 days). All restrictions ended 27 Jul.
- **Triggers:**
  - Stage III is considered when demand exceeds **90% of treatment capacity** (DMWW CEO, IPR).
  - Lawn watering can be **up to 40%** of summer demand (CIWW).
  - The 2025 ban-lift rule was "at least one source ≤10 mg/L". In practice, the 2025 lift came when the infiltration gallery stayed below 10 mg/L.
  - By 8 Jun 2026, the Raccoon had been above 10 mg/L for 136 days and the Des Moines River for 117.
- **Capital:** the state appropriated $25M, and the expansion is estimated at $40M, with ratepayers covering the difference (KCCI, Sept 2026).
- **INRS (Feb 2025 edition, Section 2 Table 2):** nitrate-N concentration reduction as mean (SD):

  | Practice | Reduction |
  |---|---|
  | Rye cover crop | 31 (29) |
  | Oat cover crop | 28 (2) |
  | Extended rotation | 42 (12) |
  | CRP | 85 (9) |
  | Energy crops | 72 (23) |
  | MRTN rate | 10 |
  | Fall→spring timing | 6 (25) |
  | Inhibitor | 9 (19) |
  | Bioreactor | 43 (21) |
  | Saturated buffer | 50 (13) |
  | Wetland | 52 |

  - **Nonpoint share:** 92% of Iowa stream N (Section 1). Section 2 Table 1 gives 93% nonpoint and 7% point.
- **Kaspar (ARS):** over 14 years near Ames, rye cut nitrate load by 57% and concentration by 59%.
- **Money:** IDALS pays $30/ac first-time and $20/ac returning, on up to 160 ac. The Greater Des Moines Watershed pays $25/ac on up to 500 ac (660 ac combined). The insurance discount is $5/ac, has no acreage cap, and does not apply to acres in other cost-share programs. Custom drilling is $19.05/ac and aerial seeding $14.70/ac (ISU 2026).
- **USGS:** drainage areas are 3,441 mi² (Van Meter) and 6,245 mi² (2nd Ave). Both sites carry the 99133 in-situ nitrate series.
- **New facts:**
  - `inrs_nonpoint_share_pct`, `inrs_rye_corn_yield_pct`.
  - `rye_before_soybean_yield`: ARS/Severo Silva 2024. Rye did not reduce soybean yield in 27 of 28 location-years, and gave no yield gain.
  - `extended_rotation_marsden`: Davis et al. 2012, via the ARS record. Similar or greater yields and profit with lower synthetic N and herbicide.
  - `stage3_trigger_demand_pct`, `lawn_watering_share_pct`, `nrf_vs_demand`, `restrictions_2025_start`, `ban_2026_residential_eased`.
  - `prairie_strips_nitrate`: **secondary**. The ISU/STRIPS pages are blocked.

## What changed
1. **2026 ban:** homes were released on **1 Jul**, not 20 Jul. The "42 days" figure applies only to businesses and governments. Homes were under the ban for 23 days.
2. **2026 facility run:** not continuous. Avoid KCCI's "193 straight days".
3. **2026 Raccoon peak:** 17.45 (25 Jan) is not the 2026 high. The USGS sensor daily mean reached **18.6 on 28 May 2026**, which includes provisional data.
4. **Q1 2026 note:** CIWW says the 2026 *capital* costs come in early 2027, not the "full 2026 costs".
5. **INRS footnotes:**
   - Sidedress vs pre-plant is 7 (37), not about 4%.
   - The oat value (28) and the MRTN value (10) moved from unverified to primary.
6. **INRS 2024 Science Team update:** it revises several efficiencies, but the Feb 2025 INRS still prints the old table:

   | Practice | Feb 2025 table | 2024 update |
   |---|---|---|
   | Rye | 31 | 28 (26), corn yield 0 instead of −6 |
   | Oat | 28 | 25 |
   | 4+ yr rotation | 42 | **27 (25)** |
   | 3-yr rotation | — | 15 (34) (new) |
   | Energy crops | 72 | 87 |
   | Inhibitor | 9 | 5 |
   | Bioreactor | 43 | 24 |
   | Saturated buffer | 50 | 45 |
   | Wetland | 52 | 30 |

   Label whichever set the app uses.
7. **Rye seed cost:** "$41.65/ac" in A1-88 is *prairie* broadcast seeding, not rye. ISU A1-92 gives about $25/ac of added rye seed cost.
8. **Fertilizer price:** the AMS price is still secondary. As a primary fallback, ISU A1-88 (July 2026) budgets N at **$0.53/lb**.
9. **Sources:** `water_people_served`, `plant_om_cost_2025_usd`, `capital_state_grant_usd` and `nasa_nfews_prior_art` now point to pages I read. The NASA project partners are DMWW, Cedar Rapids and Iowa City. The name "NFEWS" is not on the IPR page.

## Still not primary
- **EQIP 340 / 328:** NRCS booklet unreachable. 328 is `unverified`.
- **AMS anhydrous $1,096/ton:** secondary.
- **ISU ~30 lb N/ac/yr:** blocked hosts.
- **Kaspar 15-48% at other sites:** SARE blocked.
- **Cover crop acres 3.87M:** IDALS confirms only "nearly 4 million" for 2024.
- **Polk County study 70-80% agriculture:** report not opened. KCCI states 80%.
- **NCI cancer associations:** source host blocked.
- **Prairie strips 72% / 70%:** source host blocked.
- **2025 peak conflicts:** IPR Aug 2025 figures (19.39 / 16.66) not reopened. USGS daily-mean maxima for 2025: Raccoon 18.4 on 7 Jun, Des Moines 17.0 on 12 Jun.

## Avoid claiming
- That 2025 or 2026 set a **record concentration**. 2026 set a record for **duration** (193 days).
- "193 straight days".
- "42-day ban for everyone in 2026".
- That nitrate **causes** cancer. Say that studies found associations.
- That the **$1.2B** CIWW program is a nitrate cost. It is growth-driven. The nitrate expansion is about $40M.
- That INRS percentages are field-load guarantees. They are mean *concentration* reductions with large SDs. Edge-of-field values apply only to the water a practice treats, and the 2024 update prefers lb N per treated acre.
- That prairie-strip numbers compare with tile-drainage practices. They are groundwater and surface-runoff measurements from small non-tiled watersheds.
- "Nonpoint = agriculture". Say "nonpoint (mostly agricultural) sources, 92%".

## App wiring note
`notes/frontend.md` says the KPI strip reads the keys `people_served`, `plant_days_<Y>`, `plant_cost_<Y>_usd`, `ban_days_<Y>` and `fert_price_usd_lb_N`. The `facts.json` ids are `water_people_served`, `plant_days_2025/2026`, `plant_cost_2025_usd`, `ban_2025_days`/`ban_2026_days` and `fert_price_usd_lbN`. The pipeline copy step (or `factsMap`) needs an alias map. I did not rename the ids.
