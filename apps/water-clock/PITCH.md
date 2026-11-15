# Water Clock: pitch

Seven slides (title, hook, then five) and a 30-second video script. Every number is from `web/data/*.json` or a cited source and is
listed in [CLAIMS.md](CLAIMS.md). Numbers marked † are outside facts we could only corroborate through web search, not by opening the
source; use the exact wording given here.

---

## Slide 1: Title

**Water Clock**
*How many years of irrigation water are left under your field, and how many years a new rotation buys back.*

Big number: **69 years** left under the typical irrigated acre in western Kansas. Likely range **24 to 100+**. And **one irrigated
acre in seven (15%) has under 25 years**.

The 69 depends on the years used for the trend: **59 to 77 years** with 2001-2026 or 2016-2026 instead of 2011-2026. Our window starts at
the 2011-2013 pumping peak, and pumping in 2016-2025 was about 28% lower, so the clock may lean short if recent management holds.

Small print: Western Kansas Groundwater Management Districts 1, 3, 4 (26 counties). Built on NASA GRACE, POWER, IMERG, MODIS, HLS and
NEX-GDDP-CMIP6 (plus NASADEM for well checks). NASA Space Apps 2026, Field Shift. Team MOGPERS.

---

## Slide 2: The hook

**The aquifer under western Kansas is running out, and it runs out field by field.**

- Farmers here pump about **2 million acre-feet a year** for irrigation (state water-use reports, 2016-2025). Irrigation is **98%** of the
  reported irrigation plus town water use in these counties.
- **15% of irrigated acres have fewer than 25 years** before the aquifer is thinner than 30 ft, the level the Kansas Geological Survey
  uses as a rough minimum for large-volume irrigation.
- Some county clocks are already near zero: **Wichita 0, Hamilton 2, Wallace 4 years**.
- These 26 counties are home to about **171,000 people** and sold about **$2.5 billion of crops** in 2022 (Census 2025 estimates; USDA
  Census of Agriculture 2022).
- † Kansas's governor said in January 2025 that some parts of western Kansas "don't have groundwater enough to last another 25 years".

Visual: the county map coloured by years left (red under 10, orange 10-25, yellow 25-50, teal 50-100, blue 100+).

---

## Slide 3: Your Water Clock

**One number per field, with an honest range.**

- 13,233 irrigation wells; the 12,907 over the mapped aquifer each have a clock at 15, 30 or 50 ft.
- Built from 929 monitoring wells (winter levels 2011-2026), adjusted for weather with NASA POWER, plus saturated thickness at 917 wells.
- Example: **Finney County**, the largest irrigated county (195,000 reported acres): **45 years** (range 24 to 99) for the typical
  irrigated acre. Saturated thickness 150 ft, falling 2.3 ft a year.
- Every clock also shows its **2045 climate stress test** (NASA NEX-GDDP-CMIP6): Finney loses about 3 to 6 years under SSP2-4.5.
- The shortest clocks are where the aquifer is already thin (GMD 1: 7 years). Southwest Kansas has thick water but falls fastest (GMD 3:
  68 years, falling 1.7 ft a year).

Visual: screenshot of the field view for well 22769 in Finney County (`#farmer/field/22769`): gauge "45 years, likely range 24 to 99".

---

## Slide 4: What a rotation buys back

**Shift the crop, slow the clock. Here is the trade-off, honestly.**

| If every irrigated corn acre in Gray County moves to... | County clock (now 31 years) | Water saved, acre-ft/yr | Income, $/acre (Gray) |
|---|---|---|---|
| Stays continuous irrigated corn | 31 years | 0 | 360 |
| Corn-wheat-sorghum, limited irrigation | **36 years** (gain +4.7; +3.1 to +9.5) | 22,176 | 291 |
| Irrigated sorghum | **36 years** (gain +5.1) | 23,654 | 405 |
| Dryland wheat-sorghum-fallow | **49 years** (gain +18) | 62,257 | 81 |

- In Gray County our model finds irrigated sorghum earns as much as corn while pumping about 38% less (in 9 of 26 counties sorghum income
  is at or above corn; sorghum yields after 2009 are estimated from NASS ratios).
- The gains above assume the decline shrinks only in proportion to pumping. The water balance says pumping alone would cause more decline
  than observed in 20 of 26 counties (water flows back in), so gains are likely larger: in Gray, +5.6 instead of +4.7 years for the
  limited-irrigation rotation.
- Region-wide, moving **half** of irrigated corn to the limited-irrigation rotation saves about **172,000 acre-feet a year**, 8% of
  reported groundwater irrigation pumping.
- **Cutting pumping has worked here before.** In the Sheridan-6 local enhanced management area (GMD 4), farmers aimed for a 20% cut and achieved
  **35% over four years**; the KGS said the decline went from about **2 ft a year to about 5 inches a year** "without affecting the bottom
  line" (KGS news release, 2017). In state reports, Sheridan County's irrigation pumping fell 14% in 2013-2017 compared with 2008-2012.

Visual: the community slider (`#community/county/20069`) at 100%, sentence "the county clock gains +4.7 years".

---

## Slide 5: The water clock, seen from space

**NASA's GRACE satellites weigh the water. They see the same fall and the same drought dips as the wells.**

- GRACE/GRACE-FO water storage over our region was about **24 cm lower in January-August 2026 than in 2003**.
- GRACE-DA groundwater indicator for the region: **2.5th percentile in September 2026** (8.3 by November) compared with the same time of
  year in 1948-2012. It is a drought index, not a volume.
- GRACE and the wells share the long-term fall and the drought dips: **r = 0.86** for yearly levels (0.49 for year-to-year changes).
- Honest caveat on screen: GRACE's long-term trend is about **4 times smaller** than the wells show (-0.9 vs -4.0 cm a year), possibly
  (untested) because GRACE sees a few hundred kilometres at once and blends this loss with a wider area. We use GRACE to check timing, not
  to set the clock.

Visual: the GRACE chart (percentile line over 2002-2026) next to the GRACE map going red.

---

## Slide 6: Tested on the past, stressed by the future

**Does the clock work?** We hid water levels after a cut-off year and predicted the next 10 years.
- **80% ranges held the truth 83-93% of the time** (8 tests; 87-91% for 10-year change). That is why every clock shows a range.
- Trained through 2004, when declines sped up: error **6.6 ft vs 12.2 ft** for "no change".
- Trained through 2014, when declines slowed: **6.1 ft vs 6.3 ft** for "no change" on the same wells; for wells the model never saw (the
  test that matches a field clock), "no change" did as well or better (5.9 vs 6.6 ft). The model over-predicted the drop after 2014.

**Climate 2045** (NASA NEX-GDDP-CMIP6, 5 models): reference ET rises **5.9%** (SSP2-4.5) to **8.3%** (SSP5-8.5). Corn needs about
**1.2 to 1.8 more inches** of water a year. The region clock loses about **5 to 17 years** under SSP2-4.5 and **7 to 26 years** under
SSP5-8.5: the low end counts only extra pumping, the high end uses the model's own fitted response of water levels to weather, which also
counts lower recharge. The 2035-2055 change is applied from today, so near-term effects are overstated.

---

## Slide 7: Why it matters, what's next

- **For a farmer:** your field's clock, three to five strategies with water, years gained, income, evidence and risks. Decision support, not
  a replacement for your agronomist.
- **For a county or district:** a slider that turns "what if 30% of corn switches?" into years, acre-feet and dollars.
- **All open, all real data:** 8 datasets from NASA missions and models (GRACE/GRACE-FO via GFZ GravIS, GRACE-DA, POWER, IMERG, MODIS,
  HLS, NEX-GDDP-CMIP6, NASADEM), Kansas well and pumping records, USDA crops and prices. Every number is traceable.
- **Next:** add the KGS section-level aquifer base (should reduce the ~18 ft thickness error), JPL GRACE mascons with an Earthdata login, OpenET
  field water use, and irrigated-specific costs including pumping energy.

---

## 30-second video script

| Time | Voice-over | On screen |
|---|---|---|
| 0:00-0:05 | "NASA's GRACE satellites have watched western Kansas lose water for twenty years." | GRACE chart dropping; text: **GRACE: about 24 cm less water than in 2003** |
| 0:05-0:11 | "Water Clock turns that into years per field: 69 for the typical acre, under 25 for one acre in seven." | Big counter "69 years", "range 24 to 100+"; red stat **15% of irrigated acres: under 25 years** |
| 0:11-0:17 | "Click your well. Here: 45 years, maybe 24, maybe 99." | Open `#farmer/field/22769` (Finney): gauge "45 years, range 24 to 99" |
| 0:17-0:24 | "Try a new rotation. In Gray County, sorghum on every corn acre adds about five years and keeps the income." | Open `#community/county/20069`, sorghum swap, slider to 100%: "31.1 → 36.2 years" |
| 0:24-0:30 | "Water Clock. Know your years. Choose your next crop." | Logo; text: **Real NASA data. Honest ranges. NASA Space Apps 2026** |

About 70 words.

Wording notes for the presenter:
- Say "about" and give the range; never present a central estimate as a forecast.
- "0 years" means the central estimate is already below 30 ft; many wells there still pump at reduced capacity.
- Do not say GRACE confirms the size of the loss; it confirms the timing.
- Gains assume neighbours on the same part of the aquifer make the same change.
- The 69 years leans on the 2011-2026 trend window; say "59 to 77 depending on the years used" if asked.
