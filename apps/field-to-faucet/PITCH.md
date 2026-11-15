# Field to Faucet: pitch

NASA Space Apps 2026 · Challenge: "Field Shift: Adapting Farms with NASA Data" · Demo: 7 slides or a 30-second video.

Every number here is listed in `CLAIMS.md` with its source and status. Ranges are 10th-90th percentiles ("8 in 10") of
4,000 simulations. Scenario numbers come from `web/data/scenarios.json` (run 2026-11-15). Screenshots are in `web/qa/`.
To regenerate them, run `node web/qa/run_qa.cjs http://localhost:8000/`.

Rules for whoever presents:
- Say "about" and give the range for every modelled number. Say "indicative" for ban days and "estimate" for cost.
- Give the ban as "up to 56 days (homes: 40)" for 2025 and "23 days for homes, 42 for businesses" for 2026.
- Say "mostly from farmland". Statewide, 92% of the nitrogen in Iowa streams comes from nonpoint sources. Never say
  "caused by farms".
- Say "the Raccoon River at Van Meter, upstream of the intake". Do not say "at the intake". Do not claim the tap water met the standard
  (no stored source); talk about the river.
- Do not say "first nitrate forecast". A NASA-funded University of Iowa river-nitrate forecast already exists. Our
  addition is field-level timing and farmer options, joined to the city's costs.
- Do not say "fertilizer farmers already paid for", "193 straight days" or "record nitrate". The 2026 record was for
  plant days. Do not say cover crops "will" prevent a ban.

---

## Slide 1: Bare fields, bitter water

**Hook:** "Twice in two summers, 600,000+ people around Des Moines were told to stop watering their lawns. The reason
was nitrate washing off farmland upstream."

- Central Iowa Water Works imposed its first-ever lawn-watering ban in June 2025, then a second one in June 2026.
- The nitrate comes mostly from farmland. Statewide, 92% of the nitrogen in Iowa streams is from nonpoint sources. For
  these rivers, a Polk County study puts the farm share at about 80%.
- NASA satellites can see when that farmland sits bare on wet soil. That is when it leaks.

**Visual:** `web/qa/city-hero-1280.png` (the headline and the "1 in 4" impact slider).

**Speaker note:** "Des Moines drinks from the Raccoon and Des Moines rivers. In 2025 and again in 2026, the nitrate in
them was so high that the utility asked more than 600,000 people to stop watering their lawns. Most of that nitrate
comes off farm fields. Field to Faucet uses NASA data to show farmers when their own field leaks and what keeps the
nitrogen in place. It also shows the city what that would save."

## Slide 2: 2025: 112 treatment days, a lawn-watering ban of up to 56 days

- In 2025 the **Raccoon River at Van Meter**, upstream of the intake, was above the 10 mg/L drinking-water level on
  **115 of 356 measured days** (USGS). That is about 1 day in 3. The nitrate-removal plant and the ban are what the city
  pays to keep the river out of the tap.
- The nitrate-removal plant ran **112 days** and cost about **$2.2M**, including $0.6M of capital. The lawn-watering
  ban lasted **up to 56 days** (12 June-7 August; homes: 40 days).
- 2026 was worse. The plant ran a record **193 days** between January and July (not continuously). The ban lasted
  **23 days for homes and 42 for businesses and governments**.

**Visual:** `web/qa/city-full-1280.png`, cropped to "The 2025 record, with sources" KPI strip. Each tile links to the
USGS sensor or the utility.

**Speaker note:** "These are the utility's numbers and USGS sensor counts. The plant treats 10 million gallons a day
against a normal demand of 70 to 80 million. So in a bad summer the utility has to cut demand, and lawn watering is up
to 40% of it. The previous record run was 177 days in 2015. In the first quarter of 2026 alone, operating costs were
about $660,000."

## Slide 3: NASA sees the leak: bare soil + wet soil

- **HLS (Landsat + Sentinel-2, 30 m)** shows living cover vs bare soil on 1,769 forty-acre fields. The fields sit bare
  **92% of October-May**. A field counts as living when its NDVI is 0.30 or higher.
- **MODIS (250 m, every 8 days since 2011)** gives the bare share of all cropland in the watershed. **NASA POWER
  root-zone wetness (GWETROOT) and rain** show when water drains through the soil. **GPM IMERG** checked POWER's
  storm days (38 days, 2016-2021: the same volumes, but POWER smooths the peaks).
- Together they make the **leak calendar**: 91% of the modelled leak falls October-May, and 54% falls April-June.
- HLS sees winter cover on only **~1-4% of fields a year**, against ~17% adoption statewide. This is a lower bound:
  thin or late rye stays below the greenness threshold.

**Visual:** `web/qa/farmer-panel-1280.png` (leak calendar lit up in March-May, NDVI curve with the 0.30 line). Inset:
the "What NASA sees" strip from `web/qa/method-1280.png`.

**Speaker note:** "No single dataset shows the leak. HLS shows when a field has no living roots. POWER shows when the
root zone is wet enough to drain into the tiles. MODIS covers the whole 25,000 km² watershed. We checked POWER's rain
against IMERG. IMERG after May 2021 needs Earthdata access, which our build environment did not have."

## Slide 4: Better rotations for my field

A field near Rockwell City (F00179), median leak: about **14 lb N/acre/yr** reaching the river (8 in 10 years:
0.2-32).

| option | N kept, lb/acre/yr (long-run mean; 8 in 10 years) | cost, $/acre/yr | cost-share, $/acre | yield risk |
|---|---|---|---|---|
| Cereal rye before soybean | **2.1** (0-5.9); wet 2016: ~11 | $12-28 | state $20-30; Greater Des Moines Watershed $25; EQIP ~$74 (third-party figure) | low |
| 4-year corn-soy-oats-alfalfa | **3.7** (0-11) | not verified | program listed, rate not verified | moderate |
| Prairie on 10% of the field | **1.2** (0-2.8) | $26-33 | CRP CP-43 (about 75% lower cost) | low |
| Today's corn-soy | 0 (reference) | $0 | – | low |

- Rye's effect comes from trials. The Iowa Nutrient Reduction Strategy (2024 update) finds rye cuts drainage nitrate
  concentration by **28% averaged over the rotation** (SD 26), or **30% in the soybean year**. Soybean yield was not
  hurt in **27 of 28** Midwest location-years.
- The satellites tell you **when and where**. The trials tell you **how much**.
- This is decision support, not a replacement for your agronomist.

**Visual:** `web/qa/farmer-cards-1280.png` (comparison table and strategy cards).

**Speaker note:** "We are honest about size. Rye only sits ahead of soybean every other winter, so on this field it
keeps about 2 lb an acre a year on average and about 11 in a wet year like 2016. At $0.53-0.70 per lb, that nitrogen
is worth a dollar or two an acre. The farmer's case rests on cost-share, soil and erosion. The city's case rests on the
water. The sliders re-rank the cards by what matters to the farmer: nitrogen, yield safety, soil or cost."

## Slide 5: 1 in 4 more acres covered = 16 fewer treatment days

**X = 25%:** cover added on 25% of *all* upstream corn and soy acres, on top of the ~17% covered today. Coverage goes
from about 17% to about 42%. Replayed on the river USGS measured in 2025:

- About **6.5 million lb of nitrogen** (2.1-9.9 million) kept out of the rivers, counted at the gauges.
- About **16 fewer treatment-plant days** (3-34), counted only on days the plant really ran. That is **about $234k**
  of operating cost avoided (estimate; 8 in 10: $47k-507k) at $14k-16k per day. Avoided days are often
  partial-output days; at the Q1-2026 average daily cost the figure is ~$134k.
- A lawn-watering ban about **3 weeks shorter** (23 days, 9-31; indicative, proxy rule). The Raccoon River would have
  been above 10 mg/L on **7 fewer** days (2-16), because it sat far above the limit.
- **Trials only: 10 fewer plant days (2-36).** The headline mixes two methods: half the simulations use Iowa trial
  results, and half use a sensitivity from our river model. The river-model half has no tested skill, and it drives
  more of the plant-day effect.

**Visual:** `web/qa/city-replay-1280.png` (measured line, shaded "nitrate kept out of the river" band, delta tiles at
25%). Optional: `web/qa/city-hotspots-1280.png` (where to start).

**Speaker note:** "We never use the model's absolute 2025 level, because it missed that level. Instead we take the
measured river and cut each day by what more living cover removes. The plant rule was fitted to 2025 and tested on
2026. It caught 157 of the 193 run days and never fired while the plant was off. Ban days are the least certain
result. The cost is operating cost only: the plant's $40M expansion is not avoided. Soils store nitrate, so the river
takes more than one season to respond. The hotspot map shows where to start: six sub-watersheds cover 9% of the
Raccoon basin and carry 15% of the modelled leak. That ranking is not validated."

## Slide 6: Tested on years it never saw

- **Pre-registered test.** We fixed the split before fitting: train 2016-2022, test 2023-2025. On the test years, the
  satellite-and-weather model explains **62%** (Raccoon) and **56%** (Des Moines) of day-to-day nitrate changes (NSE).
  "The usual level for the date" explains 30% and 27%.
- **The 2025 miss, shown in the open.** The Raccoon was above 10 mg/L on 115 measured days. Our pre-registered model
  said **6**. The rivers carried about **1.7-2.1×** the nitrate that weather and bare ground explain.
- **What we learned.** A carry-over version built afterwards gets **83 of 115** days and passes a blind 2013 check
  (**81 vs 92** measured days). It is post-hoc, so we keep it off the headline. The app uses the model only for
  relative what-ifs applied to the measured river.
- **14-day outlook.** Its squared error is **20-25%** lower than assuming "no change" (Raccoon, 2023-2025). It has
  **no probability skill at 14 days**, and the page says so.

**Visual:** `web/qa/method-1280.png` ("Where the model fails" box and the validation tables).

**Speaker note:** "The model beats climatology and a conceptual model. It loses to 7-day persistence, which is handed
last week's measurement. One explanation for the 2025 miss is nitrogen left over after the 2020-2023 drought. We
treat that as a hypothesis, because 2023, right after a drought year, ran low. The river cannot test how much a
practice cuts nitrate. Those numbers come from trials. The full detail is in VALIDATION.md."

## Slide 7: Pilot for spring 2027

- **Data:** use NASA Earthdata to add SMAP root-zone soil moisture, IMERG V07 rain after May 2021 and the full HLS
  archive. Replace our 40-acre grid cells with real field boundaries.
- **Partners:** county Soil and Water Conservation District offices and the cost-share programs: state $20-30/acre,
  Greater Des Moines Watershed $25/acre on up to 500 acres in 22 counties, and NRCS EQIP. They can point 2027
  sign-ups at the bare-and-wet fields first.
- **Validation:** a few nitrate sensors inside the Raccoon basin to test the hotspot map, plus farmer records (N rate,
  tile, actual cover) to test the field leak.
- **The ask:** introductions to Central Iowa Water Works and the Greater Des Moines Watershed program, and NASA
  Earthdata support for a weekly operational version. It would sit alongside the NASA-funded University of Iowa
  river forecast.

**Visual:** `web/qa/city-375.png` and `web/qa/farmer-375.png` side by side ("on a phone in the field"), with arrows
"field" → "faucet".

**Speaker note:** "Everything runs on open data and a static web page, and it can be updated every week. The state put
$25M toward the $40M plant expansion. Keeping nitrogen in the fields is the other half of the answer. Field to Faucet
is decision support for the farmer and the utility, not a replacement for agronomists or engineers."

---

## 30-second video script

Voiceover: 68 words. NASA is on screen from 0:00 and spoken at 0:05.

| time | voiceover | shot / on-screen text |
|---|---|---|
| 0:00-0:05 | "Twice in two summers, 600,000 people around Des Moines were told to stop watering their lawns." | `city-hero-1280.png`, slow push-in on the headline. Corner badge "NASA HLS · MODIS · POWER · IMERG". Text: "Lawn-watering bans 2025 + 2026 · 600,000+ people · CIWW" |
| 0:05-0:11 | "NASA satellites show when farm fields sit bare on wet soil, when nitrate washes into the rivers." | `farmer-panel-1280.png`: leak calendar, March-May highlighted. Text: "Bare soil (HLS) + wet soil (POWER) = leak" |
| 0:11-0:18 | "Field to Faucet shows farmers when their field leaks, and which rotation keeps the nitrogen in the ground." | `farmer-cards-1280.png`: pan across the comparison table. Small text: "Decision support, not a replacement for your agronomist" |
| 0:18-0:25 | "Replay 2025 with one in four more acres under winter cover:" | `city-replay-1280.png`: measured line, then the shaded "nitrate kept out" band. Text: "+25% of upstream corn/soy acres (~17% → ~42%)" |
| 0:25-0:30 | "about sixteen fewer nitrate-treatment days for the city." | `city-hero-1280.png` crop of the four tiles. Text: "~16 fewer plant days (3-34) · model estimate · trials only: 10". End card: "Field to Faucet · NASA Space Apps 2026" |

Shot list (all existing screenshots; animate with pans and zooms):
1. `web/qa/city-hero-1280.png`: headline, then the four impact tiles (used at 0:00 and 0:25).
2. `web/qa/farmer-panel-1280.png`: leak calendar and NDVI curve.
3. `web/qa/farmer-cards-1280.png`: comparison table and cards.
4. `web/qa/city-replay-1280.png`: replay chart at 25%.
5. End card: title, challenge name and the NASA data badges (text only).
