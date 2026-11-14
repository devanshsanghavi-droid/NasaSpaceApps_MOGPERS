# Module `strategy`: farmer-view strategy engine

Built 2026-11-14. Script: `model/strategy.py` (re-runnable, ~1 min; Python `/home/user/venv-db/bin/python`).
Outputs: `web/data/strategies.json` (1.42 MB, compact schema), `model/outputs/strategies_summary.json`.
Frontend reader: `web/js/farmer.js` (decodes the compact schema; still reads the old mock format).
Rerun it after the model module regenerates `sim_county_crop.parquet` / `sim_state.pkl.gz`.

## Inputs (all read, none written)
| input | used for |
|---|---|
| model/outputs/sim_county_crop.parquet | per county x crop simulated drought loss cost ratio (lcr) for each NASA POWER weather year 1981-2024, liability/acre 2020-2024, history flag |
| model/outputs/sim_state.pkl.gz | the 101 fitted loss models (point + 100 block-bootstrap refits). They are used to (a) recompute every rotation and delta per bootstrap draw and (b) predict missing county-crops. Before use, the script checks that the point model reproduces `lcr_sim` exactly. If the file is missing or does not match, it falls back to approximate intervals |
| model/outputs/diversity_effect.json | `app_effect.r` rotation scenario (est 0.14, lo 0, hi 0.90) and the verdict |
| model/outputs/hazard_features.parquet | county climatology (1991-2020 JJA precipitation, EDD30), used for flags |
| data/processed/rma_state_year.parquet, rma_county_year.parquet | state liability/acre and irrigated insured share per crop (2020-2024), county insured irrigated share of corn |
| data/processed/county_static.parquet | Census irrigated share, SSURGO AWS 0-150 cm (flags) |
| data/processed/nass_county_year.parquet, nass_prices.parquet | county yields and state prices, 2019-2023 |
| data/raw/nass/rows_7state_survey_2000_2025.tsv | official NASS **state** and **US** yields (fallback when county yields are suppressed) |
| data/raw/ers/{corn,soybeans,wheat,sorghum}.csv | USDA ERS Commodity Costs and Returns, downloaded by the script from https://www.ers.usda.gov/data-products/commodity-costs-and-returns (`/media/4962/corn.csv`, `4976/soybeans.csv`, `4978/wheat.csv`, `4972/sorghum.csv`) |
| data/raw/ers/eib-222.pdf | USDA ERS EIB-222 (2021), Table 3: rye cover-crop seed cost $14.26 ± 2.03/ac (corn fields 2016), $16.27 ± 5.96 (soybean fields 2018); cost-share range $12-92/ac (2018) |
| shared/evidence/evidence_priors.json | trial / meta-analysis effect sizes (E1 cover crop, E4 extended rotation, E5 corn-soy vs continuous corn). Every number in the card text is read from this file by prior_id |
| web/data/county_bill.json, regional_summary.json | county 2045 bill change (flag text), share_3plus now, regional 2045 change |

## Coverage
- **615 counties** have cards, out of 640 with a simulated bill. The rule: corn sim with ≥ 5 insured years 2001-2024, plus a soybean sim row. The 25 excluded counties are mostly western SD/NE wheat-sorghum counties without insured soybeans, plus a few MO/MN counties with thin corn history.
- Every county has all 4 rotation classes (labels exactly as in focus_fields.json). Cards per class: corn-soy 4, continuous corn 5, 3+ crop 3, with perennial 3. That makes 15 cards per county, ≥ 3 including current (BUILD_RULES rule 6).
- Drought-tolerant swap: **sorghum in 346 counties**, where the county has ≥ 5 insured sorghum years or the state insures ≥ 20,000 sorghum acres/yr (KS, MO, NE, SD). **Wheat in 269 counties** (IA, MN, most of IL).
- Crop loss-cost sources:
  - Wheat: county 401, thin history 127, pooled 87 (75 IA counties use the US wheat liability/acre).
  - Sorghum: county 187, thin 118, pooled 41.
  - Soybeans: county 601, thin 14.
  - "Pooled" means the bootstrap models predict the county's own weather years with crop = wheat/sorghum. The credibility factor is 1 (no local history), the irrigated share is the state's insured share for that crop, and the liability/acre is the state's (the US value if the state insures < 10,000 acres/yr). These are flagged on the card.

## Method
**Rotations** (weights per acre-year): corn-soy = ½ corn + ½ soy; continuous corn = corn; 3+ crop = ⅓ corn + ⅓ soy +
⅓ wheat; with perennial = ½ corn + ½ soy for the row-crop years only. Hay/alfalfa years are not in the bill because there
is no county forage model. This is labelled on the card.

**Drought bill.** For each hazard year y and bootstrap draw b:
S_b(y) = Σ_crop w × m × lcr_b,crop(y) × liab/acre_crop (2020-2024).
Expected = mean over the 44 years, 1-in-5 = p80, 1-in-10 = p90. Crops are summed within the same hazard year, so the tails combine correctly.
- est = point model at r_est.
- lo/hi = the 5th/95th percentile over the 100 bootstrap draws, taking the envelope over r ∈ {0, 0.14, 0.90} for scenario cards.
- Deltas (strategy − current) are computed within each draw, so the intervals carry the correct correlation.

These are parameter intervals. They carry the same caveat as the model module: 39% county coverage in the out-of-time test.

**Rotation scenario.** The multiplier is m = 1 − r for corn in a 3+ crop rotation ("3+ crop", "with perennial",
`cs_small_grain`) and for corn after soybean in `cc_to_cs`. It is m = 1 for corn in corn-soy and continuous corn.
r comes from diversity_effect.json. It is a scenario based on the Bowles et al. 2020 trial range, not an estimate: the county data
found no robust effect. It applies to corn only, because Bowles is maize-specific. (The model module's county slider applies
the same r to the whole principal-crop bill.) Kluger et al. 2022 found the rotation benefit about 29% smaller in the hottest
temperature quintile (computed from the priors: 1 − 0.85/1.19). This appears as a risk on the card.

Known inconsistency: continuous-corn and corn-soy "current" both use the county-average insured corn. The `cc_to_cs` card
therefore shows a lower bill than the corn-soy "current" card in the same county, by the scenario amount. The card states this
("continuous-corn bill probably understated").

**Cover crop.** No drought-loss reduction is invented. delta_bill = null and the UI shows "not quantified"; the bill is
shown unchanged. Grade is "thin". The real benefits are listed qualitatively with numbers from evidence_priors:
- interrill erosion −54% and rill erosion −90% (Kaspar 2001)
- infiltration +34.8% (Basche 2019)
- SOC +4% (He 2025)
- tile nitrate load −61% (Kaspar 2007)

Risks: soil-water depletion (Nielsen 2016, Great Plains) and the Deines 2023 yield contrasts.

**Income** (`delta_income_per_ac`, $/acre/yr vs current) = revenue minus operating costs:
- Revenue = NASS county yield (fallbacks: state, then the same-ERS-region states, then US) × NASS state marketing-year price (US price when missing).
- Costs = ERS "Total, operating costs" per planted acre. Region map: IA/IL/MN/MO = Heartland, KS/NE = Prairie Gateway, SD = Northern Great Plains. Sorghum uses Prairie Gateway everywhere, the only Corn Belt/Plains region ERS publishes for 2019-2023.
- Computed for each year 2019-2023. est = mean of the 5 yearly deltas; lo/hi = min/max over the years under the low/high evidence assumptions.
- Yield assumptions:
  - Continuous-corn yield = county yield − 1.03 t/ha (16 bu/ac; Kluger 2022). The `cc_to_cs` range runs from 2.5% (Kluger 2025, net) to 18.5% of CC yield (Al-Kaisi 2015).
  - `cs_small_grain`: corn 0 (−3.4% Kluger 2025 to +4% Davis 2012), soybean 0 (0 to +9% Davis 2012).
  - Cover crop: corn −2.3% (−4.6% Pantoja to 0% Marcillo), soybean +0.2% (−3.1% He 2025 US to +0.2%), minus rye seed cost (EIB-222). Seeding and termination costs and cost-share are **not** included, and the card says so.
- Excluded: insurance premiums and indemnities, land, machinery and overhead.
- NASS yields are per harvested acre while ERS costs are per planted acre. This is a small mismatch.

**ERS cost status: fetched OK.** 2019-2023 mean operating costs ($/planted acre):
- Heartland: corn 414, soybeans 219, wheat 221.
- Prairie Gateway: corn 367, soybeans 212, wheat 128, sorghum 163.
- Northern Great Plains: corn 361, soybeans 169, wheat 146.

All values are in strategies_summary.json.

**County flags** (templates in `flags`, values in `ctx`):
- irr_high (≥ 25% irrigated, from max(Census share, RMA insured corn share)): "insured losses here are mostly on dryland acres…"
- irr_some (10-25% irrigated)
- dry_summer (JJA precipitation < 260 mm)
- hot (EDD30 JJA ≥ 50)
- low_aws (< 200 mm)
- ww_drought (KS, or dry NE/SD): winter-wheat drought not seen by the May-Aug model
- c45: county 2045 change, SSP2-4.5

Card-level flags cover thin or pooled crop loss costs and the yield or price fallbacks. Flag counts: c45 615, ww_drought 164, hot 135, irr_high 124, low_aws 95, dry_summer 84, irr_some 66.

## `strategies.json` compact schema (`schema: "compact-v1"`)
```
{schema, schema_doc, generated_at, mock:false, units, dollar_year, interval_method, income_method,
 scenario:{r:{est,lo,hi}, label, source},
 fields:["expected_bill","bill_1in5","bill_1in10","delta_bill","delta_bill_1in10","delta_income_per_ac"],
 rotations:{<class>:{mix}},
 strategies:[{id, name, short, description, why, benefits[], gaps[], risks[], evidence:{grade, sources:[{label,url}]},
              income_note, scenario?:true, not_quantified?:text}],
 flags:{<code>:{text (with {irr},{prcp},{edd},{aws},{c45},{s3p}), cards:[strategy ids] | null (= card-level flag)}},
 counties:{<fips>:{n, st, ctx:{irr,prcp,edd,aws,c45,s3p}, f:[county flag codes], src:{crop:county|thin|pooled|pooled_us},
                   lpa:{crop: liability $/insured acre 2020-24},
                   rot:{<class>:[{s: strategy_id, v:[18 numbers = est,lo,hi per field; null = not quantified/n.a.],
                                  f:[card flag codes]}]}}}}
```
Strategy ids: `current`, `cc_to_cs` (continuous corn only), `cs_small_grain` (corn-soy and continuous corn),
`cover_crop`, and exactly one of `dt_sorghum` / `dt_wheat`. Delta sign: negative bill delta = lower bill.

## Example numbers ($/acre/yr; est [lo, hi])
**Plymouth County IA (19149), corn-soy**: current expected bill 16.8 [10.7, 21.0], 1-in-5 17.6, 1-in-10 40.9 [15.7, 56.1].
- Add small grain: bill 11.5, delta −5.3 [−14.5, −2.3], 1-in-10 delta −13.2. Net return −95 [−162, −26]. Iowa wheat yields come from IL/MN/MO, wheat history is thin, and Iowa's usual small grain is oats.
- Rye cover crop: delta not quantified; net return −26 [−59, −10].
- Wheat swap: bill 6.7, delta −10.1 [−12.8, −5.2]; net return −169 [−260, −93].

**Saline County KS (20169), corn-soy**: current 33.5 [25.8, 38.1], 1-in-10 91.5.
- Small grain: delta −10.8 [−23.3, −6.4], income −15 [−71, +59].
- Sorghum swap: delta −5.2 [−6.7, −1.3], income −32 [−109, −3].

**Saline County KS, continuous corn**: current 39.1.
- Corn-soy: delta −8.4 [−28.2, −1.4], income +24 [−105, +92].
- Sorghum: delta −10.8, income −8 [−117, +74].

**Buffalo County NE (31019), 84% irrigated**: the sorghum swap *raises* the county-average bill (+6.1 [+1.0, +10.8]). Insured sorghum there is mostly dryland and corn mostly irrigated. The irr_high flag and the sorghum gaps text explain this.

## Caveats
- The drought bill inherits the loss model's limits: May-Aug NASA POWER hazard only, so winter wheat is likely understated (KS 2023), and the 2022-2023 totals were under-predicted by about half in the test.
- A swap lowers the insured bill partly because the new crop carries lower liability per acre (less insured value). The income line shows the trade-off.
- County-average yields and loss costs mix irrigated and dryland fields, and the fields of every rotation.
- The diversity drought effect is a labelled scenario, not an estimate.
- Evidence from factcheck.md claims 6, 7, 9, 10 (Bowles, Kluger, SARE/CTIC, sorghum) is cited as reported in snippets; those originals were not opened (UNVERIFIED there).

## Browser test (Playwright, Chromium, `web/` served by `python -m http.server`)
Tested at 1280 and 375 px:
- Cases: Plymouth IA corn-soy (4 cards), Saline KS corn-soy (4), Saline KS continuous corn (5), Buffalo NE continuous corn (5), Plymouth 3+ crop (3).
- No console errors or warnings, no failed requests, no horizontal scroll (scrollWidth = viewport).
