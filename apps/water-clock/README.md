# Water Clock

**How many years of irrigation water are left under each field in western Kansas, and how many years a different rotation buys back.**

NASA Space Apps 2026, challenge "Field Shift: Adapting Farms with NASA Data". Team MOGPERS.

## What it shows

Western Kansas irrigates about 1.4 million acres (Census of Agriculture 2022) from the Ogallala / High Plains aquifer, pumping about
2 million acre-feet a year (state water-use reports, 2016-2025). The aquifer is falling. Water Clock turns decades of well measurements (KGS WIZARD 1940-2026; rates fitted on 2011-2026), reported
pumping and NASA satellite data into one number per field:
**years until the aquifer under it is thinner than 30 ft**, the level the Kansas Geological Survey uses as a rough lower limit for
large-volume irrigation.

Results for the 26 counties of Groundwater Management Districts (GMD) 1, 3 and 4, at the 30 ft threshold:

| | Years left (central) | Likely range (p10 to p90) |
|---|---|---|
| **Region** (12,907 irrigated points) | **69** | 24 to 100+ |
| GMD 1 (west central) | 7 | 0 to 100+ |
| GMD 3 (southwest) | 68 | 31 to 100+ |
| GMD 4 (northwest) | 98 | 0 to 100+ |

- **15% of irrigated acres have fewer than 25 years left.** Wichita (0), Hamilton (2), Wallace (4), Greeley (9) and Lane (13) are the
  shortest county clocks. Eight counties are at 100+ years.
- **The headline depends on the years used for the trend.** Fitted on 2001-2026 the region clock is 59 years; on 2011-2026 (used) 69;
  on 2016-2026 77. Our window starts at the 2011-2013 pumping peak, and reported pumping in 2016-2025 was about 28% lower, so the clock
  may lean short if recent management holds (`county_clocks.json` `sensitivity.decline_window`).
- **Rotations buy back years, but slowly.** If every irrigated corn acre in Gray County moved to a corn-wheat-sorghum rotation with
  limited irrigation, the county clock would go from 31 to 36 years (gain +4.7, range +3.1 to +9.5). Going dryland on those acres gives
  49 years. These gains assume the decline shrinks only in proportion to pumping; the water balance shows water flowing back in, so they
  are likely conservative (Gray limited irrigation: +5.6 years with that counted).
- **Climate makes it shorter.** With NASA NEX-GDDP-CMIP6 projections for 2045 the region clock loses about 5 to 17 years (SSP2-4.5) or
  7 to 26 years (SSP5-8.5). The low end counts only extra irrigation demand; the high end uses the model's fitted response of water
  levels to weather, which also counts lower recharge.
- **GRACE sees it from space.** GRACE/GRACE-FO water storage over the region was about 24 cm lower in January-August 2026 than in 2003.
  Its yearly values track the wells (r = 0.86 for annual levels; 0.49 for year-to-year changes), but its long-term trend is about 4 times
  smaller than the well-based estimate (see [VALIDATION.md](VALIDATION.md)).

Every number above comes from `web/data/*.json` and is listed in [CLAIMS.md](CLAIMS.md).

## The app

Four views, all static (no server code):
1. **My field.** Click any of 13,233 irrigation wells (WIMAS points of diversion). See its clock with a range, and strategy cards for
   current irrigated corn, a limited-irrigation corn-wheat-sorghum rotation, dryland wheat-sorghum-fallow, irrigated sorghum and,
   in 7 southern counties, irrigated cotton. Each card shows water use, years gained, income per acre, evidence, gaps and risks.
2. **My county.** County and district clocks, with a slider: "if X% of irrigated corn shifts to strategy Y, the county clock gains Z years".
3. **From space.** GRACE-DA groundwater percentiles over time and as a map, and the wells-vs-GRACE comparison.
4. **Proof & data.** Hindcast tables, the 2045 climate shift, every data source with its status, and caveats.

### Run it

```
cd apps/water-clock/web && python3 -m http.server 8000
# open http://localhost:8000/
```

MapLibre GL 4.7.1 and Chart.js 4.4.4 load from pinned CDNs. If `web/data/` files are missing the app falls back to `web/mock/`
and shows a red MOCK DATA banner. With the committed data no banner appears.

### Regenerate the data

Raw downloads are cached under `data/raw/` (gitignored); processed inputs are committed in `data/processed/`. Run from
`apps/water-clock/`:

```
# 1. NASA water and climate (notes/nasa_water.md)
python3 pipeline/nasa_power.py
python3 pipeline/nasa_grace_da.py
python3 pipeline/nasa_grace_gfz.py
python3 pipeline/nasa_grace_maps.py
python3 pipeline/nasa_imerg.py
python3 pipeline/nasa_cmip6.py
# 2. Wells and aquifer base (notes/wells.md)
python3 pipeline/wells_kgs_fetch.py
python3 pipeline/wells_nwis_fetch.py
python3 pipeline/wells_base_fetch.py
python3 pipeline/wells_dem.py
python3 pipeline/wells_process.py
# 3. Reported pumping (notes/pumping.md)
python3 pipeline/pumping_fetch.py
python3 pipeline/pumping_process.py
# 4. Land: CDL, MODIS ET, HLS (notes/nasa_land.md; cdl_points and hls need wimas_use.parquet)
python3 pipeline/nasa_cdl_fetch.py
python3 pipeline/nasa_cdl_county.py
python3 pipeline/nasa_cdl_points.py
python3 pipeline/nasa_modis_et.py
python3 pipeline/nasa_hls_irrigation.py
# 5. Economics and boundaries (notes/econ.md)
python3 pipeline/econ_nass_fetch.py crops
python3 pipeline/econ_nass_fetch.py census2022
python3 pipeline/econ_nass_process.py
python3 pipeline/econ_costs.py
python3 pipeline/econ_boundaries.py
python3 pipeline/econ_context.py
# 6. Model: writes all ten web/data files (about 4 minutes, includes the trend-window sensitivity)
cd model && python3 run_all.py
```

`run_all.py` reads only `data/processed/` and checks that a 0% strategy shift reproduces every county clock exactly.

## Data sources

NASA data first. Status: used, partial (used with a gap) or blocked (see [BLOCKERS.md](BLOCKERS.md)).

| Dataset | Role in Water Clock | Status |
|---|---|---|
| **GRACE/GRACE-FO** total water storage (GFZ GravIS RL06) and G3P groundwater | Regional storage trend from space; check on the well-based decline | used |
| **GRACE-DA** groundwater percentiles (NASA data assimilation, nasagrace.unl.edu) | Weekly groundwater drought signal and map; check on the wells | partial (Oct 2025 missing) |
| **NASA POWER** daily weather + FAO-56 reference ET | Weather adjustment of decline rates; how irrigation demand responds to heat and rain; climate baseline | used |
| **GPM IMERG** daily precipitation (served by NASA POWER) | Cross-check of POWER precipitation | partial |
| **MODIS MOD16A3GF** annual ET | Relative water use of corn vs sorghum vs wheat | used |
| **HLS** (Harmonized Landsat Sentinel-2) | Test: can dry-spell greenness tell irrigated from dryland fields? | used (2 counties, 2 summers) |
| **NEX-GDDP-CMIP6** (5 models) | 2045 change in reference ET and rain, so the clock shift | used |
| **NASADEM** | Check of reported land altitude at wells | used |
| JPL / CSR GRACE mascons | Preferred volumetric GRACE | blocked (no Earthdata login; CSR TLS failure) |
| KGS WIZARD water levels and USGS groundwater levels | Winter water levels 1940-2026: the core of the clock | used |
| USGS base of aquifer (OFR 98-393) + KGS bedrock picks; USGS 2009 saturated thickness (SIR 2012-5177) | Aquifer base; cross-check | used |
| Kansas WIMAS water use | Reported pumping, acres and crop per well, 1990-2025 | partial (Sherman 1998 missing) |
| USDA Cropland Data Layer | Crop at each well and county acreage | used |
| USDA NASS (yields, prices, Census of Agriculture 2022), ERS costs | Income per acre, irrigated acres | partial (county irrigated yields end 2018) |
| Census population and boundaries; USGS GMD polygons | Towns, maps | used |
| OpenET (NASA-supported, not a NASA dataset), KSU budgets, BEA earnings | Field ET; irrigated costs; share of economy | blocked |

## Method in plain words

1. **How fast is the water table falling?** For each of 929 monitoring wells we take the winter water level each year (2011-2026).
   We first remove the part of each year's change explained by the previous summer's weather (NASA POWER rain and reference ET), so the
   rate means "average weather". A Kalman filter (local level plus trend) gives each well's rate. Wells are pulled toward their county
   average when their own record is noisy (empirical Bayes). Rates are then mapped between wells by kriging.
2. **How much water is left?** Saturated thickness = water-table elevation minus the elevation of the aquifer base. We compute it at
   917 wells with a reliable base and krige it to every field. The base map is coarse, so each field carries about +/-22 ft of base
   uncertainty.
3. **Years left** = (saturated thickness - 30 ft) / decline rate. We draw 10,000 random combinations of thickness and rate (including how
   much decline rates change from decade to decade, about 35%) and report the 10th, 50th and 90th percentiles. Rising or flat water
   levels give "100+". A county value is the acre-weighted median over its irrigated wells.
4. **Pumping and decline.** Across the 26 counties, long-term water-level decline tracks reported pumping closely (R² = 0.90). The slope
   gives an apparent specific yield of 0.20 (80% range 0.19 to 0.23): about 5 ft of decline per foot of water pumped over the aquifer area.
5. **Strategies.** Water use per crop comes from what farmers report to the state (WIMAS): corn 14.6 in/acre, sorghum 10.3, wheat 8.9.
   Pumping saved = acres switched x (old water use - new water use). Less pumping lowers the pumping part of the decline rate in
   proportion (the conservative reading), and the clock is recomputed. In 20 of 26 counties the water balance says recent pumping alone
   would cause more decline than observed (net inflow from recharge and return flow), so the top of each gain range lets the decline
   respond more than in proportion. Income = NASS county yield x Kansas price - ERS operating cost, 2016-2025.
6. **Climate 2045.** CMIP6 changes in reference ET and rain change irrigation demand by the response measured in WIMAS
   (0.36 in more water per extra inch of reference ET), which raises the decline rate (low end). The high end applies the model's own
   fitted response of winter water levels to growing-season weather (-0.13 ft per inch of reference ET, +0.08 ft per inch of rain),
   which also includes recharge.

Details and all settings: [notes/model.md](notes/model.md). Per-source details: `notes/*.md`.

## Validation in brief

Full results: [VALIDATION.md](VALIDATION.md).
- **Hindcast, trained on data through 2014, predicting the change to about 2024:** average error 6.1 ft per well, against 6.3 ft for
  "no change". That edge is small, and the model loses on RMSE and for wells it never saw (6.6 vs 5.9 ft). Declines slowed after 2014,
  and the model predicted about twice the decline that happened.
- **Trained through 2004, when declines sped up:** the model roughly halves the error of "no change" (6.6 vs 12.2 ft) and beats every
  simple baseline.
- **80% ranges contained the truth 83-93% of the time** (87-91% for 10-year change), so the ranges are honest, slightly wide.
- **The field clock corresponds to the spatial test** (kriged rates at places without a monitoring well). There, after 2014, "no change"
  was as good as the model; the model was much better when declines sped up (2004 fold: 7.6 vs 13.2 ft).
- **Saturated thickness** rebuilt for 2009 matches the published USGS 2009 map with r = 0.97 and an average error of 18 ft.
- **GRACE** agrees with the wells on timing (r = 0.86 for yearly levels, 0.49 for year-to-year changes) but shows a 4x smaller
  long-term loss.
- **HLS** dry-spell greenness separates irrigated from dryland corn with 92% accuracy (kappa 0.83) on a balanced test set.

## Limitations

- **The clock extrapolates the 2011-2026 rate.** It is not a forecast of what farmers or water managers will do. Rates have changed by
  about a third between decades. The ranges include that, but not a policy change, and not the choice of trend window (59 to 77 years
  for the region; Ford 50 to 84, Gray 24 to 42).
- **Saturated thickness is uncertain by about 20-30 ft at a field** because the aquifer-base map is coarse (200 ft contours plus KGS picks).
  The more detailed KGS section database was on a blocked host.
- **Thin-aquifer counties** (GMD1, Hamilton, Wallace) show 0 to a few years at 30 ft. Many wells there still pump below 30 ft at
  reduced capacity; the 15 ft view is more useful there.
- **Strategy gains assume neighbours change too.** One field switching alone barely moves the water table under it.
- **Income** uses ERS costs that mix irrigated and dryland farms and leave out pumping energy. Irrigated yields after 2018 are
  estimated from older NASS ratios. Limited-irrigation corn yield is a linear interpolation.
- **WIMAS acres are about 1.4x Census irrigated land** because several wells can report the same field. We use WIMAS acres together
  with WIMAS water use so the two stay consistent.
- **Wallace County** is in GMD4 per our county list, although 90% of its irrigated acres lie inside the GMD1 boundary. Moving it
  changes GMD1 from 7 to 5 years and GMD4 from 98 to 100+.
- **County clocks describe irrigated land** (WIMAS points weighted by acres), not the whole county, and not town water supplies.
  We did not link town public-supply wells to the clock.
- **The 2014 hindcast is not fully blind:** model variants were compared on both test periods while building.
- **Not used:** OpenET, JPL/CSR GRACE mascons, KSU irrigated budgets, BEA farm earnings (all blocked). See [BLOCKERS.md](BLOCKERS.md).

This is decision support, not a replacement for your agronomist or your groundwater management district.

## Files

| Path | What |
|---|---|
| `web/` | Static app; `web/data/*.json` = model outputs |
| `pipeline/` | Data fetch and processing scripts |
| `data/processed/` | Committed processed inputs |
| `model/` | State model, clock, water balance, validation, GRACE comparison, rotation engine |
| `notes/` | One note per module: sources, URLs, columns, coverage, failures |
| `CONTRACTS.md` | Build contract |
| `VALIDATION.md`, `CLAIMS.md`, `PITCH.md`, `BLOCKERS.md` | Validation, claims register, pitch, blocked sources |

## Team

Team MOGPERS, NASA Space Apps 2026. Code, data processing and docs were built with AI coding agents (Claude) working under the
team's build rules (`docs/BUILD_RULES.md`): real data only, every number traceable in CLAIMS.md.
