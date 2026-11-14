# Water Clock: pitch

Seven slides (title, hook, then five) and a 30-second video script. Every number is from `web/data/*.json` or a cited source and is
listed in [CLAIMS.md](CLAIMS.md). Numbers marked † are outside facts we could only corroborate through web search, not by opening the
source; use the exact wording given here.

---

## Slide 1: Title

**Water Clock**
*How many years of irrigation water are left under your field, and how many years a new rotation buys back.*

Big number: **69 years** left under the typical irrigated acre in western Kansas. Likely range **24 to 100+**.

Small print: Western Kansas Groundwater Management Districts 1, 3, 4 (26 counties). Built on NASA GRACE, POWER, IMERG, MODIS, HLS and
NEX-GDDP-CMIP6. NASA Space Apps 2026, Field Shift. Team MOGPERS.

---

## Slide 2: The hook

**The aquifer under western Kansas is running out, and it runs out field by field.**

- Farmers here pump about **2 million acre-feet a year** for irrigation (state water-use reports, 2016-2025). Irrigation is **98%** of the
  reported irrigation plus town water use in these counties.
- **15% of irrigated acres have fewer than 25 years** before the aquifer is thinner than 30 ft, the level the Kansas Geological Survey
  uses as a rough minimum for large-volume irrigation.
- Some county clocks are already near zero: **Wichita 0, Hamilton 2, Wallace 4 years**.
- † Kansas's governor said in January 2025 that some parts of western Kansas "don't have groundwater enough to last another 25 years".

Visual: the county map coloured by years left (red under 10, orange 10 to 25, teal 50 to 100, blue 100+).

---

## Slide 3: Your Water Clock

**One number per field, with an honest range.**

- 13,233 irrigation wells, each with years left at 15, 30 or 50 ft.
- Built from 929 monitoring wells (winter levels 2011-2026), adjusted for weather with NASA POWER, plus saturated thickness at 917 wells.
- Example: **Finney County**, the largest irrigated county (195,000 reported acres): **45 years** (range 24 to 99). Saturated thickness
  150 ft, falling 2.3 ft a year.
- The shortest clocks are where the aquifer is already thin (GMD 1: 7 years). Southwest Kansas has thick water but falls fastest (GMD 3:
  68 years, falling 1.7 ft a year).

Visual: screenshot of the field view: clock gauge with "45 years, likely range 24 to 99".

---

## Slide 4: What a rotation buys back

**Shift the crop, slow the clock. Here is the trade-off, honestly.**

| If every irrigated corn acre in Gray County moves to... | County clock (now 31 years) | Income, $/acre (region) |
|---|---|---|
| Stays continuous irrigated corn | 31 years | 366 |
| Corn-wheat-sorghum, limited irrigation | **36 years** (gain 3.5 to 11) | 236 |
| Irrigated sorghum | **37 years** | 297 |
| Dryland wheat-sorghum-fallow | **52 years** | 53 |

- Region-wide, moving **half** of irrigated corn to the limited-irrigation rotation saves about **172,000 acre-feet a year**, 8% of all
  reported pumping.
- **It has worked here before.** In the Sheridan-6 local enhanced management area (GMD 4), farmers aimed for a 20% cut and achieved
  **35% over four years**; the KGS said the decline went from about **2 ft a year to about 5 inches a year** "without affecting the bottom
  line" (KGS news release, 2017). In state reports, Sheridan County's irrigation pumping fell 14% in 2013-2017 compared with 2008-2012.

Visual: the community slider at 100%, sentence "the county clock gains +5.3 years".

---

## Slide 5: The water clock, seen from space

**NASA's GRACE satellites weigh the water. They see the same drop as the wells.**

- GRACE/GRACE-FO water storage over our region: **+5 cm in 2003, -19 cm in 2026** (January-August average).
- GRACE-DA groundwater percentile for the region in September 2026: **2.5**, near the bottom of its record.
- Year by year, GRACE and our 929 wells move together: **r = 0.86**.
- Honest caveat on screen: GRACE's long-term trend is about **4 times smaller** than the wells show (-0.9 vs -4.0 cm a year), likely because
  its ~300 km view blends this loss with a wider area. We use GRACE to check timing, not to set the clock.

Visual: the GRACE chart (percentile line over 2002-2026) next to the GRACE map going red.

---

## Slide 6: Tested on the past, stressed by the future

**Does the clock work?** We hid all water levels after 2014 and predicted them.
- Average error **6.1 ft** per well over 10 years, about the same as "no change" (6.3 ft). Declines slowed after 2014, so the model
  over-predicted the drop.
- Trained through 2004, when declines sped up: **6.6 ft vs 12.2 ft** for "no change".
- **80% ranges held the truth 87-93% of the time.** That is why every clock shows a range.

**Climate 2045** (NASA NEX-GDDP-CMIP6, 5 models): reference ET rises **5.9%** (SSP2-4.5) to **8.3%** (SSP5-8.5). Corn needs about
**1.2 to 1.8 more inches** of water a year, and the region clock loses about **5 years** (range 2 to 10) to **8 years** (range 6 to 9).

---

## Slide 7: Why it matters, what's next

- **For a farmer:** your field's clock, three to five strategies with water, years gained, income, evidence and risks. Decision support, not
  a replacement for your agronomist.
- **For a county or district:** a slider that turns "what if 30% of corn switches?" into years, acre-feet and dollars.
- **All open, all real data:** 8 NASA datasets, Kansas well and pumping records, USDA crops and prices. Every number is traceable.
- **Next:** add the KGS section-level aquifer base (would cut the ~20 ft thickness error), JPL GRACE mascons with an Earthdata login, OpenET
  field water use, and irrigated-specific costs including pumping energy.

---

## 30-second video script

| Time | Voice-over | On screen |
|---|---|---|
| 0:00-0:04 | "Under western Kansas, the water that grows the crops is running out. But how fast, under *your* field?" | Aerial map of center pivots fading to the county map. Text: **Water Clock** |
| 0:04-0:10 | "Water Clock answers in years. For the typical irrigated acre: 69 years, likely 24 to more than 100. For 15% of acres, under 25." | Big counter "69 years" with "range 24 to 100+"; map turns red in Wichita, Hamilton, Wallace. Text: **15% of irrigated acres: under 25 years** |
| 0:10-0:16 | "Click any of 13,000 irrigation wells. See your clock, built from decades of well records and NASA weather data." | Cursor clicks a Finney field: gauge "45 years, range 24 to 99" |
| 0:16-0:22 | "Then try a new rotation. In Gray County, moving all irrigated corn to a limited-irrigation rotation adds about 5 years. Going dryland adds 21." | Slider moves to 100%; "31 → 36 years"; cards show $/acre. Text: **Fewer gallons, more years. Here is the cost.** |
| 0:22-0:27 | "And NASA's GRACE satellites see the same water disappearing from space." | GRACE chart dropping; text: **GRACE storage: +5 cm (2003) → -19 cm (2026)** |
| 0:27-0:30 | "Water Clock. Know your years. Choose your next crop." | Logo; text: **Real data. Honest ranges. NASA Space Apps 2026** |

Wording notes for the presenter:
- Say "about" and give the range; never present a central estimate as a forecast.
- "0 years" means the central estimate is already below 30 ft; many wells there still pump at reduced capacity.
- Do not say GRACE confirms the size of the loss; it confirms the timing.
- Gains assume neighbours on the same part of the aquifer make the same change.
