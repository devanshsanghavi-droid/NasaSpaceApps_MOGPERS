# Water Clock (branch `water-clock`)

**One line:** For every irrigated field over the Ogallala (High Plains) aquifer in western Kansas, Water Clock shows how many years of irrigation water are left under it. It also shows how many years each rotation buys back, and what that costs or earns.

## Why judges will feel it (verify each fact again before it goes on a slide)
- **50-year outlook:** a Kansas State study (Steward et al. 2013, PNAS) projected that about 69% of the aquifer's stored groundwater in Kansas would be depleted in 50 years if trends continue. The same study said reducing pumping now extends the aquifer's life and total production.
- **Remaining life varies hugely:** from about 10-25 years in parts of western Kansas to more than 100 years elsewhere. The Kansas governor has said some areas have less than 25 years left.
- **Irrigation dominates:** it accounts for about 80-90% of pumping (USGS).
- **NASA can see it from orbit:** GRACE/GRACE-FO gravity measurements show the southern High Plains losing about 2.5 cm of water per year (NASA/JPL PIA16840, 2003-2012).
- **Proof that cutting back works:** Kansas's Sheridan-6 LEMA, a local enhanced management area, cut pumping, with reported small effects on profit. Verify the numbers (KSU / Kansas Water Office evaluations).

## Users and views
1. **Farmer view.** Click a field or a water-right point and see:
   - **Your Water Clock:** years until saturated thickness falls below a usable-irrigation threshold (for example 30 ft, with sensitivity shown), with an uncertainty range.
   - **Strategy cards:**
     - current (often continuous irrigated corn)
     - corn-wheat-sorghum with limited irrigation
     - dryland wheat-sorghum-fallow
     - a cotton or sorghum swap where suitable
   - **Each card shows:** water use (inches per acre from ET), years gained, expected net income from NASS yields and AMS prices, yield risk under drought, soil-health effects, information gaps and risks needing local review.
2. **Community view.** County and district water clocks, with a slider: "if X% of irrigated corn shifts to strategy Y, the county clock gains Z years." Show the towns and the share of local economy that depend on the aquifer.

## Technical core
- **Groundwater state.** The 3 sources below are fused in a Bayesian or state-space model per area. It estimates decline rate and its drivers, with uncertainty from specific yield and recharge.
  - Kansas Geological Survey WIZARD well water levels (annual winter measurements, decades of record).
  - The KGS High Plains aquifer saturated-thickness surfaces.
  - **GRACE/GRACE-FO** groundwater storage anomalies as the regional constraint. Use nasagrace.unl.edu GRACE-DA products if there is no Earthdata login.
- **Pumping and crop water use.**
  - Reported pumping per water right comes from Kansas WIMAS (public).
  - Crop ET by field comes from satellite: OpenET if a key is available; otherwise USGS SSEBop, MODIS 16A3GF, or an HLS-based crop-coefficient model driven by NASA POWER reference ET.
  - Irrigation status comes from HLS greenness during dry spells versus IMERG rainfall.
  - CDL provides the crops.
- **Rotation-to-water link.** Learn net pumping per crop and rotation (pumping minus effective precipitation), and the response of water level to pumping in each area. A strategy changes net withdrawal, which changes the decline rate and therefore years remaining.
- **Climate.** NEX-GDDP-CMIP6 changes in ET demand and precipitation shift the clock by 2045.
- **Validation:** hindcast water-level decline in held-out wells, out of time. Compare GRACE regional trends with aggregated well declines.

## NASA data and its role
| Dataset | Role |
|---|---|
| GRACE/GRACE-FO | Regional groundwater depletion: the "clock" seen from space |
| ECOSTRESS / OpenET / MODIS ET / HLS | Crop water use per field |
| GPM IMERG and NASA POWER | Precipitation and reference ET |
| SMAP | Soil moisture context, optional |
| SRTM | Terrain |
| NEX-GDDP-CMIP6 | Future climate |

Partner data: CDL, KGS WIZARD and WIMAS, USGS NWIS groundwater, NASS, AMS.

## Impact metrics to compute and show (all with ranges)
- years of irrigation water remaining, per field and per county
- years gained per strategy
- acre-feet saved
- income change per acre
- county economic exposure
- years until wells in the main town fail, where a public-supply well can be linked (verify before claiming)

## Demo moments
1. **The clock itself:** a farm field with "11 years left (range 7-16)".
2. **Drag the slider:** shift to a wheat-sorghum rotation and the clock goes to "19 years".
3. **NASA from space:** a GRACE map showing the region going red, matching the wells.

## Region
Western Kansas Groundwater Management Districts 1, 3 and 4. A focus county could be Finney, Haskell, Scott, Wichita or Sheridan; choose by data availability.
