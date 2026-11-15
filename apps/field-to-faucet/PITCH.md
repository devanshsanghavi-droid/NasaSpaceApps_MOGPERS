# Field to Faucet: pitch

NASA Space Apps 2026 · Challenge: "Field Shift: Adapting Farms with NASA Data" · Demo: 7 slides or a 30-second video.

Every number on these slides is in `CLAIMS.md` with its source and verification status. Ranges are 10th-90th
percentiles ("8 in 10"). Screenshots are in `web/qa/` (regenerate with `node web/qa/run_qa.cjs http://localhost:8000/`).

Rules for whoever presents:
- Say "decision support, not a replacement for your agronomist" on the farmer slide.
- Say "about" and give the range for every modelled number. Say "indicative" for ban days.
- Do not say "record nitrate" (2026 set a record for plant **days**), "193 straight days", or "a 42-day ban for
  everyone" (homes: 23 days in 2026).
- Do not say cover crops "will" prevent a ban. Say what the replay shows.

---

## Slide 1 (title): Field to Faucet

**Title:** Field to Faucet: NASA satellites show when farm fields leak nitrate, and what that costs the tap

- Two summers running, about 600,000 people in central Iowa were told to stop watering their lawns.
- The reason: nitrate in the rivers Des Moines drinks from, mostly from farmland upstream.
- We show each farmer when their field leaks and which rotation keeps the nitrogen in the field, and show the city what
  that means for its water.

**Visual:** full-bleed `web/qa/city-top-1280.png` (hero: plant days, cost, ban days, the "1 in 4 more fields" slider).

**Speaker note:** "In June 2025 Central Iowa Water Works imposed its first-ever lawn-watering ban. In June 2026 it did it
again. Both times the cause was nitrate in the Raccoon and Des Moines rivers. In Iowa, 92% of the nitrogen in streams
comes from nonpoint sources, mostly farmland. NASA satellites can see when that farmland is bare and the soil is wet.
That is when it leaks."

## Slide 2 (intro): The problem, in numbers

**Title:** What one year of nitrate cost Des Moines

- **115 days** above the 10 mg/L drinking-water limit at the Raccoon River intake in 2025 (about 1 day in 3 with a
  measurement; USGS sensor).
- The nitrate-removal plant ran **112 days** in 2025 and cost about **$2.2M** ($1.6M operating, $0.6M capital). In 2026
  it ran a record **193 days**.
- A **56-day** lawn-watering ban in 2025 (12 June-7 August) for more than 600,000 people.

**Visual:** the KPI strip (`web/qa/city-top-1280.png`, lower half) with the source links visible, or
`model/out/fig_2025_zoom.png` (measured Raccoon line crossing the red 10 mg/L limit).

**Speaker note:** "These are the utility's numbers and the USGS sensor's numbers, each linked in the app. The plant
treats 10 million gallons a day against 70 to 80 million of demand, so in a bad year the utility asks people to stop
watering lawns. The previous record run was 177 days in 2015; 2026 beat it. The Des Moines River, the second source,
was above the limit on 105 measured days in 2025."

## Slide 3: What NASA sees

**Title:** The leak calendar: bare ground + wet soil + storms

- **HLS (Landsat + Sentinel-2), 30 m:** living cover vs bare soil on 1,769 forty-acre fields. They sit bare 92% of
  October-May, and only about 2.5% of field-winters show a living cover crop.
- **MODIS 13Q1, 250 m:** how much of the watershed's cropland is bare, every 8 days since 2011.
- **NASA POWER root-zone wetness (GWETROOT) and rain**, checked against **GPM IMERG** storms: when water drains through
  the soil.
- Put together, 91% of the modelled leak falls October-May, 54% in April-June.

**Visual:** `web/qa/farmer-field-1280.png` (leak calendar lighting up March-June) next to the NASA strip ("What NASA
sees"). Optional inset: the NDVI curve of one field with the 0.30 living-cover line.

**Speaker note:** "No single dataset shows the leak. HLS shows when a field has no living roots. POWER shows when the
root zone is wet enough to drain into the tiles. MODIS gives the whole 25,000 km² watershed. IMERG let us check POWER's
storm days: same volumes, but POWER smooths the peaks. The cover-crop share HLS sees is a lower bound: thin rye can stay
below the greenness threshold."

## Slide 4: The farmer view

**Title:** My field: when it leaks, and what stops it

- Click your field: a typical field here loses about **14 lb of nitrate-N per acre per year** to the river (long-run
  mean 13.7; a single year ranges 0.8-31).
- Strategy cards compare today's corn-soy with **cereal rye before soybean**, a **4-year rotation with oats and
  alfalfa**, and **prairie on 10% of the field**: why, evidence, N kept, yield risk, soil health, gaps, local risks.
- Rye before soybean: Iowa trials cut drainage nitrate **28% on average (SD 26)**; no soybean yield loss in **27 of 28**
  Midwest location-years; cost **$12-27.50/acre/yr**, cost-share **$20-30/acre** (state), **$25** (Greater Des Moines
  Watershed), about **$74** (EQIP 340, to confirm with NRCS).
- Decision support, not a replacement for your agronomist.

**Visual:** `web/qa/farmer-panel-1280.png` (strategy cards with N-kept bars, the priority sliders, "who pays" links).

**Speaker note:** "We are honest about size. For the median field, rye before soybean keeps about 1.7 lb N per acre per
year on average, more in a wet year (about 9 in 2016), because it only sits ahead of soybean every other winter. The
4-year rotation keeps about 3.7. At $0.53-0.70 per pound that fertilizer value is small, a dollar or two an acre, so the
case for the farmer rests on cost-share, soil health and erosion, and the case for the city rests on the water. The
practice effects come from Iowa trials, not from our satellites; the satellites tell you when and where."

## Slide 5: The city view

**Title:** Replay 2025 with 1 in 4 more fields under living cover

- On the river USGS actually measured in 2025, 25% more upstream acres with winter living cover gives about **23 fewer
  removal-plant days (5-41)**, about **$350k** less operating cost ($73k-620k), and about **23 fewer ban days (9-31,
  indicative)**.
- About **6.5 million lb of nitrogen** (2.1-10.0 million) kept out of the two rivers: fertilizer farmers already paid for.
- Few Raccoon exceedance days flip (about **8 of 115**, range 2-16), because the river sat far above the limit; the
  plant and ban respond more because they turn on near 10 mg/L.
- Half the simulations use Iowa trial results, half our NASA-driven river model; added on top of today's ~17% adoption.

**Visual:** `web/qa/city-replay-1280.png` (measured line, the shaded "nitrate kept out of the river" band, delta tiles at
25%). Optional: `web/qa/city-map-1280.png` (hotspot map).

**Speaker note:** "We never use the model's absolute 2025 level, because it missed it. We take the measured river and cut
each day by what trials and our model say more living cover removes. The plant and ban days come from proxy rules: the
plant rule was fitted to 2025 and tested on 2026, where it caught 157 of 193 run days and never fired when the plant was
off. Ban days are the least certain. Cost is operating cost only: the $40M expansion is not avoided. And soils store
nitrate, so a real change takes more than one season to show."

## Slide 6: Validation and honesty

**Title:** Tested on years it never saw, including the year it got wrong

- Trained 2016-2022, tested 2023-2025: the satellite-and-weather model explains **62%** (Raccoon) and **56%** (Des Moines)
  of day-to-day nitrate variation (NSE), against **30%** and **27%** for "the usual level for the date".
- **The 2025 miss:** 115 measured days above 10 mg/L; our pre-registered model said **6**. The rivers carried about
  **1.7-2.1×** the nitrate that weather and bare ground explain.
- What we learned: a carry-over version built afterwards gets **83 of 115** and passes a blind 2013 test (**81 vs 92**
  days), but it is post-hoc, so the app uses the model only for relative what-ifs on the measured river.
- The 14-day outlook beats "no change" by **20-25%** in squared error, but has **no probability skill at 14 days**; we
  say so on the page.

**Visual:** `model/out/fig_v1_v2_2023_2026.png` (v1, v2 and measured, 2023-2026) or `web/qa/method-1280.png`.

**Speaker note:** "We wrote the test split down before fitting. The model beats climatology and a conceptual model, but
loses to 7-day persistence, which is handed last week's measurement. In 2025 it missed badly. Leftover nitrogen after
the 2020-2023 drought is one explanation; we treat it as a hypothesis, because 2023, right after a drought, ran low.
What the river cannot test is how much a practice cuts nitrate. Those numbers come from trials, and the sub-watershed
hotspot ranking is not validated: there are no gauges inside the basin. All of this is in VALIDATION.md."

## Slide 7: What's next and the ask

**Title:** From hackathon to the 2027 planting season

- **Data:** Earthdata access to pull SMAP root-zone soil moisture, IMERG V07 storms after May 2021, and the full HLS
  archive, all blocked in our build environment.
- **Validation:** a handful of nitrate sensors inside the Raccoon basin to test the hotspot map; farmer records (N rate,
  tile, actual cover) to test field leak.
- **Pilot:** work with Central Iowa Water Works and the Greater Des Moines Watershed cost-share program ($25/acre) to
  point sign-ups at the bare-and-wet fields first.
- **The ask:** introductions to the utility and the watershed program, and NASA Earthdata support for an operational
  version.

**Visual:** the two-view map (`web/qa/city-map-1280.png` beside `web/qa/farmer-map-1280.png`) with arrows "field" →
"faucet".

**Speaker note:** "Everything runs from open data and a static web page; it can be updated weekly. The state put $25M
toward a $40M plant expansion. Keeping nitrogen in fields is the other half. Field to Faucet is decision support for the
farmer and the utility, not a replacement for agronomists or engineers."

---

## 30-second video script

Voiceover: 73 words.

| time | voiceover | shot / on-screen text |
|---|---|---|
| 0:00-0:05 | "Two summers running, 600,000 people around Des Moines were told to stop watering their lawns." | Sprinkler shut off / dry lawn; text: "Lawn-watering bans: 2025 and 2026 · ~600,000 people · CIWW" |
| 0:05-0:09 | "The reason: nitrate, mostly from farm fields upstream." | River chart from the app crossing the red 10 mg/L line; text: "115 days above the limit in 2025 · USGS" |
| 0:09-0:15 | "NASA satellites show when each field sits bare while storms soak the soil." | Zoom from MODIS watershed to HLS 40-acre squares; leak calendar lights up Mar-Jun; badges "HLS · MODIS · POWER · IMERG" |
| 0:15-0:21 | "Field to Faucet shows farmers which rotation keeps that nitrogen in the field," | Farmer view: click a field, strategy cards slide in, "Rye before soybean: 28% avg cut (Iowa trials)"; small text "Decision support, not a replacement for your agronomist" |
| 0:21-0:30 | "and shows the city the payoff: replay 2025 with one in four more fields covered, and the removal plant runs about 23 fewer days." | City replay: slider moves to 25%, shaded band appears, tile "~23 fewer plant days (5-41) · model estimate"; end card "Field to Faucet · NASA Space Apps 2026" |

Shot list:
1. Lawn / sprinkler B-roll (own footage or a free-licence clip; no utility logos).
2. Screen capture: city view river chart, 2025 range, Raccoon (`#city`).
3. Screen capture: hotspot map, then farmer map zoom (`#farmer`), leak calendar of a sample field ("pick a sample field").
4. Screen capture: strategy cards and priority sliders.
5. Screen capture: replay slider dragged from 0% to 25%, delta tiles updating.
6. End card with title, challenge name and the data badges.
