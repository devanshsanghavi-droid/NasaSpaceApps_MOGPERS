# Drought Bill (branch `drought-bill`)

**One line:** Every drought sends farmers, and taxpayers who subsidize crop insurance, a bill. Drought Bill uses NASA data to show each county and farm its expected drought bill in dollars per acre, and how much a more diverse rotation would cut it.

## Why judges will feel it (verify each fact again before it goes on a slide)
- **2022:** drought was the costliest cause of crop-insurance loss at **$7.6 billion**, in a year when indemnities hit a **record $19.1 billion** (EWG analysis of USDA RMA data).
- **2001-2022:** drought accounted for $56.6 billion, about 35% of all crop-insurance payouts.
- **2023:** crop and rangeland losses from major disasters exceeded $21.9 billion (American Farm Bureau).
- **Taxpayers:** premiums are heavily subsidized (verify the share, roughly 60%). Part of every drought bill is public money.
- **Rotation evidence:** diverse rotations reduced maize drought-year yield losses by 14-90% in long-term North American trials (Bowles et al. 2020, One Earth). Kluger et al. found rotation benefits shrink in hot years. Show the uncertainty honestly.

## Users and views
1. **Farmer view.** Pick a field or enter a county and rotation. See:
   - **Your drought bill:** expected $ per acre per year of drought loss.
   - **Bad-year bills:** the 1-in-5 and 1-in-10 year figures.
   - **Strategy cards:**
     - current (for example corn-soy)
     - corn-soy-small grain
     - a cover-crop option
     - a drought-tolerant crop swap (sorghum or wheat) where relevant
   - **Each card shows:** change in expected drought bill and tail risk, change in average income, evidence quality, information gaps and local review flags.
2. **Public view.** A national/regional county map of the drought bill (insured losses from drought per acre). A "taxpayer share" toggle. A slider: "if rotation diversity in this county rose to X, the 2012/2022-style drought bill would fall by $Y."

## Technical core
- **Drought hazard from NASA.** County-year (and field-season) indices:
  - NASA POWER/IMERG precipitation deficits during critical windows
  - heat degree-days
  - SMAP root-zone moisture percentiles (or POWER GWETROOT)
  - vegetation stress from MODIS/HLS (VCI/VHI-style)
  - optional evaporative stress index (ECOSTRESS/MODIS LST)
- **Losses.** USDA RMA Cause of Loss files (public, county x crop x cause x year, 1989-present) provide drought indemnities. RMA Summary of Business provides liability and insured acres, which together give a drought loss cost per insured acre. Add NASS yields and acres.
- **Rotation diversity.** Build it from CDL crop sequences: a per-pixel and per-county rotation diversity index, and the share of continuous corn, from 2008 onward.
- **Model.** Estimate how drought losses scale with hazard, and how rotation diversity changes that sensitivity:
  - a county panel with fixed effects
  - heterogeneous effects (causal forest / DML) with soils (gNATSGO AWS) and irrigation share as modifiers
  - honest confounding diagnostics
  - out-of-time validation: train through 2020, predict the 2022 and 2023 drought bills
- **Simulation.** Expected annual drought bill = integrate the loss function over the hazard climatology, using NASA POWER since 1981 and future shifts from NEX-GDDP-CMIP6.

## NASA data and its role
| Dataset | Role |
|---|---|
| NASA POWER, IMERG, SMAP / POWER GWETROOT, MODIS/HLS vegetation stress | Drought hazard, the core driver |
| NEX-GDDP-CMIP6 | The 2045 bill |
| HLS/MODIS | Field-level stress, drill-down |

Partner data: CDL (rotation diversity), RMA (losses), NASS, USDM (validation), gNATSGO.

## Impact metrics to compute and show (all with ranges)
- $ per acre expected drought bill, per county and per farm
- $ saved per strategy
- taxpayer dollars saved at the county and state level
- 2045 bill change

## Demo moments
1. **The bill:** a county map lights up the 2022 drought bill in red dollars.
2. **The swap:** a farmer's corn-soy card shows "$38/ac per year expected drought bill"; switching to a 3-crop rotation drops it to "$24/ac".
3. **The hindcast:** the 2022 bill predicted from 2020 data versus the actual.

## Region
Corn Belt and Plains states (at least IA, NE, KS, MO, IL, SD, MN) at county level, with a field drill-down in one county.
