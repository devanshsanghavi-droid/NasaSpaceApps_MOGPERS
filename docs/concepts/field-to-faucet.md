# Field to Faucet (branch `field-to-faucet`)

**One line:** NASA satellites can see when a farm field is leaking nitrate. Field to Faucet shows each farmer upstream of Des Moines when their field leaks and which rotation stops it. It also shows the city what that means for the tap water of 600,000 people.

## Why judges will feel it (verify each fact again before it goes on a slide)
- **June 2026:** high nitrate led to a lawn-watering ban for about 600,000 people in central Iowa (Iowa Public Radio, 2026-06-09).
- **2025:** the Des Moines nitrate removal facility ran more than 110 days, at about $2.2M for the year and up to about $16k per day (Central Iowa Water Works; KJAN; IPR 2026-01-12).
- **Leak per acre:** an average Iowa corn or soy acre loses about 30 lb of nitrate-N a year to waterways (Iowa State University).
- **Cover crops:** in 15-year Iowa State plots, a cereal rye cover crop cut N loss by 57%. Other Iowa sites show 22-48% (Kaspar, SARE).
- **Real measurements:** USGS sensors record nitrate every 15 minutes at the city's intakes: Raccoon River at Van Meter (USGS-05484500) and Des Moines River at 2nd Ave (USGS-05482000). Parameter code 99133 is nitrate+nitrite, mg/L as N.
- **Drinking-water limit:** the EPA maximum contaminant level is 10 mg/L nitrate-N.

## Users and views
1. **Farmer view (the challenge requirement).** Click a field on the map and see:
   - **Leak calendar:** the months with no living roots (from HLS) that line up with heavy rain (IMERG) and wet soil (SMAP, or NASA POWER GWETROOT).
   - **Strategy cards:** the current rotation, cereal rye before soybean, an extended rotation with oats/alfalfa or another perennial phase, and one more evidence-backed option. Each card covers why it is suggested, evidence (trials plus satellite), lb of N kept in the field, the fertilizer value of that N, yield risk, soil-health benefits, information gaps, risks needing local review, and who pays (Iowa cost-share, EQIP 340/328).
2. **City / public view.** This is the impact view.
   - A map of which upstream sub-watersheds (HUC-12s) and which fields drive the nitrate reaching the intake.
   - A **"what if X% of upstream fields add living cover"** slider. It recomputes past seasons (for example 2025) and reports days above 10 mg/L, removal-plant days, $ cost and watering-ban days avoided.
   - A **tap-water nitrate outlook** for the next 1-2 weeks, from current soil wetness, recent storms and bare-ground share.

## Technical core (no if-else lookup tables)
- **Living-cover detection:** a per-field time series of living-cover fraction from HLS (NDVI/GCVI, residue via NDTI) over 2016 to now. It detects fall/winter/spring living cover (cover crops, winter wheat, perennials). Crop sequences come from CDL.
- **Watershed river model:** a model of daily nitrate concentration and load at Van Meter (and Des Moines River at 2nd Ave), learned from the measured USGS series. Inputs are watershed-aggregated drivers with sensible lags:
  - share of cropland with living cover (HLS)
  - IMERG rainfall (antecedent amounts, storm intensity)
  - soil wetness (SMAP if Earthdata is available, otherwise NASA POWER GWETROOT)
  - temperature (mineralization)
  - snowmelt
  - crop shares by year (CDL)
  - tile-drainage proxies from SSURGO drainage class (poorly drained cropland share)
  - streamflow from NWIS
  Use a physically shaped model, such as gradient boosting with monotonic constraints on bare share and wetness, or a small two-reservoir nitrate model fitted to the data. Give it quantile outputs for uncertainty.
- **Validation:** train on 2016-2022 and test out-of-time on 2023-2025, including the 2025 crisis. Report skill against simple baselines (climatology, persistence).
- **Field attribution:** each field's leak score combines its bare-and-wet days with soil drainage and slope. Calibrate it to the watershed model so the sum across fields matches the river.
- **Scenario engine:** change each field's living-cover pattern by strategy, then propagate through the learned watershed sensitivity. Blend that with trial-based effect priors so the estimate is anchored to trials. Report ranges, not single numbers.
- **Plain-language uncertainty:** use bands and natural frequencies, and say where local validation is needed.

## NASA data and its role (must be integral)
| Dataset | Role |
|---|---|
| HLS (Landsat + Sentinel-2) | Living cover and bare soil per field, the core treatment variable |
| GPM IMERG | Storm timing and intensity that flushes nitrate |
| SMAP or NASA POWER GWETROOT | Wetness of the soil profile, which controls drainage |
| NASA POWER | Temperature and weather drivers |
| SRTM / NASADEM | Slope and flow paths |
| MODIS LST | Optional extra driver |

Partner data: CDL, SSURGO/gNATSGO, USGS NWIS (validation target), NASS.

## Impact metrics to compute and show (all with ranges and sources)
- lb of N kept per field and per watershed
- days above 10 mg/L avoided
- removal-plant days and $ avoided
- lawn-watering-ban days avoided
- people served (about 600k)
- farmer fertilizer value retained

## Demo moments
1. **Replay summer 2025:** the river nitrate line versus the model, then the slider at 25% living cover shows ban days shrinking.
2. **Click a farm:** a leak calendar lights up in April-June, and the rye card shows N kept.
3. **Upstream hotspot map** of where the nitrate comes from.

## Reuse
`shared/central_iowa_pipeline/` already fetches HLS (tile 15TVG covers Des Moines and the lower Raccoon), CDL, soils, NASADEM, POWER and IMERG. The Raccoon watershed extends west into tiles 15TUG/15TUF and others, so extend coverage and keep compute modest. 250 m MODIS NDVI is fine for watershed shares if HLS is too heavy; keep HLS for field drill-down in a focus area.
