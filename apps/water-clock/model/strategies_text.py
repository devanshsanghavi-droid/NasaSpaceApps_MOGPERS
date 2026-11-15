"""Plain-language text for the strategy cards. Numbers are filled in at run time from the data (fmt keys);
literature statements we could not re-open from the build container are marked "(unverified)" in the text."""

WIMAS_URL = "https://geohydro.kgs.ku.edu/geohydro/wimas/"
NASS_URL = "https://www.nass.usda.gov/datasets"
ERS_URL = "https://www.ers.usda.gov/data-products/commodity-costs-and-returns"
STEWARD = ("Steward, D.R. et al. (2013) Tapping unsustainable groundwater stores for agricultural production in the High "
           "Plains Aquifer of Kansas, projections to 2110. PNAS 110(37):E3477-E3486", "https://doi.org/10.1073/pnas.1220351110")
DEINES = ("Deines, J.M., Kendall, A.D., Butler, J.J. Jr., Hyndman, D.W. (2019) Quantifying irrigation adaptation strategies in "
          "response to stakeholder-driven groundwater management in the US High Plains Aquifer. Environ. Res. Lett. 14:044014 "
          "(unverified citation details)", "https://doi.org/10.1088/1748-9326/aafe39")
BUTLER = ("Butler, J.J. Jr., Whittemore, D.O., Wilson, B.B., Bohling, G.C. (2016) A new approach for assessing the future of "
          "aquifers supporting irrigated agriculture. Geophys. Res. Lett. 43:2004-2010 (unverified citation details)",
          "https://doi.org/10.1002/2016GL067879")


def cards(v):
    """v: dict of computed numbers (see run_all.strategy_numbers)."""
    return {
        "S0": dict(
            why=("This is what most irrigated land here grows now. It is the baseline the other cards are compared with: "
                 f"irrigated corn uses the most pumped water of the grain crops (about {v['corn_in']:.0f} in/acre a year, "
                 "reported to the state)."),
            evidence=[
                dict(text=(f"Kansas water-use reports, 2011-2025: single-crop irrigated corn points used a median "
                           f"{v['corn_in']:.1f} in/acre/yr across the region (year range {v['corn_lo']:.1f}-{v['corn_hi']:.1f}), "
                           f"versus {v['sorghum_in']:.1f} for sorghum and {v['wheat_in']:.1f} for wheat."),
                     source="Kansas WIMAS water-use reports (KDA-DWR / KGS)", url=WIMAS_URL),
                dict(text=(f"NASS county yields 2000-2018: irrigated corn yields varied about {v['cv_corn_irr']*100:.0f}% "
                           f"(coefficient of variation) year to year, dryland corn about {v['cv_corn_dry']*100:.0f}%."),
                     source="USDA NASS QuickStats bulk file", url=NASS_URL),
                dict(text=("Steward et al. (2013) estimated that 30% of the groundwater in the Kansas High Plains aquifer had "
                           "been pumped by 2010 and projected that another 39% would be used by 2060 at existing trends (69% in "
                           "total; a model projection, not a measurement)."), source=STEWARD[0], url=STEWARD[1]),
            ],
            benefits=["Highest and most stable yields in most years", "Familiar equipment, markets and crop insurance"],
            gaps=["Cost per acre uses USDA ERS Prairie Gateway averages that mix irrigated and dryland corn; pumping energy "
                  "cost per acre-foot is not included (no citable source was reachable)",
                  "Irrigated yields after 2018 are estimated from the 2000-2018 irrigated/all-practice ratio because NASS "
                  "stopped publishing them"],
            risks=["Uses the most water, so this field's clock runs fastest", "Exposed to well-yield decline as saturated "
                   "thickness falls: pumping capacity drops before the aquifer is 'empty'"],
            soil_health=("Continuous corn leaves a lot of residue, which protects the soil if it is kept on the surface; "
                         "but a single crop keeps pest and disease cycles going and needs the most nitrogen."),
            yield_risk="Low while the well can keep up; rises sharply in drought years if well capacity has fallen.",
            applies_where="Everywhere with irrigation today (the current practice).",
        ),
        "S1": dict(
            why=("Rotating corn with wheat and sorghum and capping irrigation spreads the water over crops that need less "
                 "of it. Corn is capped at 11 in/acre a year, one fifth of the 55-inch, 5-year allocation set for the Sheridan-6 "
                 "local enhanced management area (LEMA, 2013-2017); wheat and sorghum get what farmers here report applying "
                 "to them."),
            evidence=[
                dict(text=(f"Kansas water-use reports: Sheridan County, which holds most of the Sheridan-6 LEMA (started 2013), "
                           f"reported {v['sher_pre']:,.0f} AF/yr of irrigation in 2008-2012 and {v['sher_dur']:,.0f} AF/yr in "
                           f"2013-2017 ({v['sher_chg']:+.0f}%); neighbouring Thomas County changed {v['thomas_chg']:+.0f}%. "
                           "County totals include land outside the LEMA, and weather differs between the periods."),
                     source="Kansas WIMAS water-use reports", url=WIMAS_URL),
                dict(text=("Deines et al. (2019) estimated the Sheridan-6 LEMA used about 31% less water in 2013-2017 than a "
                           "modelled no-LEMA baseline, mostly by irrigating less and more efficiently, with some switching to "
                           "crops such as sorghum (search-corroborated; the paper itself could not be opened from the build "
                           "environment)."), source=DEINES[0], url=DEINES[1]),
                dict(text=(f"WIMAS single-crop reports, 2011-2025 region medians: wheat {v['wheat_in']:.1f} in/acre, sorghum "
                           f"{v['sorghum_in']:.1f} in/acre."), source="Kansas WIMAS water-use reports", url=WIMAS_URL),
            ],
            benefits=["Cuts pumping substantially while keeping some irrigated income",
                      "Wheat and sorghum use their water at different times than corn, which can let one well cover more land",
                      "Breaks pest and disease cycles of continuous corn"],
            gaps=["Limited-irrigation corn yield is interpolated linearly between NASS irrigated and dryland yields; real "
                  "yield response is usually less than linear (so income here is probably conservative)",
                  "ERS costs are not split by irrigation level",
                  "Rotation benefits to yield (rotation effect) are not included"],
            risks=["More management: three crops, three planting windows", "Lower income than full corn in good price years",
                   "Wheat is exposed to spring freeze and hail"],
            soil_health=("A three-crop rotation with a winter crop keeps the ground covered more of the year than continuous "
                         "corn and usually improves soil structure; less tillage helps keep that benefit."),
            yield_risk="Medium: limited water means drought years cut corn and sorghum yields more than under full irrigation.",
            applies_where="Fields with enough well capacity for limited irrigation; designed after the GMD4 Sheridan-6 LEMA.",
        ),
        "S2": dict(
            why=("Going dryland stops pumping on this field entirely. Wheat-sorghum-fallow is the standard dryland rotation in "
                 "western Kansas: the fallow year stores rain in the soil for the next crop."),
            evidence=[
                dict(text=(f"NASS county yields 2000-2018: dryland wheat after fallow averaged about {v['wheat_fallow_ratio']*100:.0f}% "
                           f"of the all-practice county wheat yield, dryland sorghum about {v['sorghum_dry_ratio']*100:.0f}% of "
                           "the all-practice sorghum yield."), source="USDA NASS QuickStats bulk file", url=NASS_URL),
                dict(text=(f"NASS county yields 2000-2018: dryland wheat yields varied about {v['cv_wheat_dry']*100:.0f}% year to "
                           f"year (coefficient of variation) versus {v['cv_corn_irr']*100:.0f}% for irrigated corn."),
                     source="USDA NASS QuickStats bulk file", url=NASS_URL),
            ],
            benefits=["No pumping: the most years added to the clock", "Lowest operating cost per acre",
                      "Keeps the water right's remaining water in the ground for later or for neighbours"],
            gaps=["The fallow year is counted with zero income and zero cost (weed-control cost in fallow is not included)",
                  "Crop insurance and government payments are not included",
                  "Converting a pivot to dryland has transition costs not modelled here"],
            risks=["Income falls a lot, and swings with rainfall", "Fallow ground can blow in dry, windy springs if residue is low",
                   "Water-right rules: long non-use can affect a right (check with KDA-DWR)"],
            soil_health=("Fallow periods leave soil bare unless residue is kept (no-till); no-till fallow stores more water and "
                         "reduces wind erosion. Dryland rotations add less organic matter than irrigated crops."),
            yield_risk="High: yields depend on rain; drought years can mean near-zero harvest.",
            applies_where="Anywhere, but best where saturated thickness is already thin or wells are weak.",
        ),
        "S3": dict(
            why=("Grain sorghum is more drought tolerant than corn and here farmers report applying about "
                 f"{(1 - v['sorghum_in'] / v['corn_in']) * 100:.0f}% less water to it ({v['sorghum_in']:.1f} vs "
                 f"{v['corn_in']:.1f} in/acre)."),
            evidence=[
                dict(text=(f"Kansas water-use reports, 2011-2025: sorghum {v['sorghum_in']:.1f} in/acre vs corn {v['corn_in']:.1f} in/acre "
                           "(region medians of single-crop points)."), source="Kansas WIMAS water-use reports", url=WIMAS_URL),
                dict(text=(f"MODIS satellite ET 2008-2024: sorghum fields evaporate about {v['modis_corn_sorg']:.1f} in/yr less than "
                           "corn fields (MODIS underestimates irrigated ET, so we use it only as a relative check)."),
                     source="NASA MODIS MOD16A3GF via Microsoft Planetary Computer", url="https://planetarycomputer.microsoft.com/dataset/modis-16A3GF-061"),
            ],
            benefits=["Uses less water with a similar machine setup to corn", "Tolerates heat and drought better"],
            gaps=["Irrigated sorghum yields are scarce in NASS (county irrigated sorghum ends 2009); estimates rest on old ratios",
                  (f"ERS sorghum costs come from mostly dryland farms (about {v['sorghum_ers_irr_pct']:.0f}% of surveyed "
                   f"acres irrigated, ERS {v['sorghum_ers_year']})")],
            risks=["Lower price per bushel than corn and fewer nearby buyers", "Sugarcane aphid and bird damage"],
            soil_health="Similar to corn; sorghum residue is durable and protects soil well.",
            yield_risk="Medium-low: sorghum keeps more yield than corn when water runs short.",
            applies_where="Most of the region; especially fields where well capacity has fallen.",
        ),
        "S4": dict(
            why=("Cotton is a warm-season crop that needs less irrigation than corn. It is already grown on some irrigated "
                 f"fields in {v['n_cotton_counties']} southern counties of the region (about {v['cotton_acres_recent']:,.0f} "
                 f"reported acres a year in 2021-2025). Points reporting cotton used about {v['cotton_in']:.1f} in/acre."),
            evidence=[
                dict(text=(f"Kansas water-use reports: cotton reported on irrigated points in {v['n_cotton_counties']} region counties "
                           f"in at least 5 years since 2011; {v['cotton_acres_recent']:,.0f} reported acres on average in 2021-2025."),
                     source="Kansas WIMAS water-use reports", url=WIMAS_URL),
                dict(text="Kansas cotton yields are only published at state level in recent years (NASS); income uses the state yield.",
                     source="USDA NASS QuickStats bulk file", url=NASS_URL),
            ],
            benefits=["Lower water use than corn", "Different market, spreads price risk"],
            gaps=["Few local cotton data: state yields, ERS Prairie Gateway costs, no county irrigated yields",
                  "Needs a gin within hauling distance (not assessed)"],
            risks=["Short growing season in the northern part of the region", "Specialised equipment and marketing"],
            soil_health="Cotton leaves little residue, so soil is more exposed to wind erosion; a cover or wheat rotation helps.",
            yield_risk="Medium: frost dates and hail; less known locally.",
            applies_where="Southern counties where farmers already report cotton (WIMAS); not recommended in the north.",
        ),
    }
