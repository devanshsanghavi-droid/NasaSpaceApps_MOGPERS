# Module `scenario` + `export`: what-if engine (m07) and web data export (m08)

```
python3 model/m07_scenarios.py     # ~40 s -> model/out/scenarios.json
python3 model/m08_export_web.py    # ~2 s  -> web/data/* (contract files), checks parse + size
cd web && python3 -m http.server   # serves web/data/*
```
Both scripts read everything at run time and are re-runnable end to end: `nwis_daily.parquet`, `model/out/{features.parquet,
models/, sensitivity.json, metrics.json, basin_index_check.json, river_daily.parquet, v2/river_daily_v2.parquet (if any),
outlook.json, fields.geojson, field_detail/, strategies.json, huc12_props.json}` and `docs/facts.json` (by id).
**After any river-model or fields rerun, run m07 and then m08.**

Numbers below are from the run of 2026-11-15 ~00:38 UTC (NWIS through 2026-11-13; m03 sensitivity rerun with the
Bayesian bootstrap at 00:30-00:35; v1 river model unchanged). This run follows an independent science review: plant days
now count only real run days, trials-only results are exported for every level, and the learned path is labelled as
having no tested skill.

## 1. The question and the lever
"What if X% more of the upstream row-crop acres (both intake basins: Raccoon at Van Meter 05484500 and Des Moines River
at 2nd Ave 05482000) grew a cereal-rye-type living cover from October to May, on top of current practice?"
X = 0, 5, ..., 50. **X is a share of ALL upstream corn/soy acres, added on top of today** (`x_definition` in
scenarios.json: "X% of all upstream corn/soy acres add cover, beyond the ~17% already covered statewide"). X = 25 takes
coverage from about 17% to about 42%. Results for every calendar year 2016-2026 (2026 partial, through Nov 13); replays for 2025 and 2026.

## 2. Method
**Impact basis: observed river, relative change.** The simulation misses the 2025-26 level (about 1.7-2x the drivers),
so absolute simulated levels are never used for counts. Each day's measured nitrate is cut by a fraction D(t):
`C'(t) = C_obs(t) x (1 - D(t))`. Flow is unchanged. Exceedance days count measured days only; loads use measured flow x
gap-filled concentration (same regression gap filler as m05).

**Path (a), trial prior.** On Oct-Jul days, `D_a = X x e x s`; the annual load cut is `dL = X x e x s x w`.
- e = INRS 2024 cereal-rye efficiency, 28% (SD 26) (`inrs_cover_rye_pct.inrs_2024_update`, `inrs_cover_rye_sd`).
  It is a normal truncated to [0, 1], with the location solved (0.166) so the draw mean is 28%. p10-p90 of e is 6-54%.
- s = share of the river load from row-crop land, U[0.759, 0.892] (`basin_index_check.json`, fields_model).
- w = share of the calendar year's measured load passing Jan-Jul + Oct-Dec. This is the fall-to-July drainage that cover
  crops act on; Aug-Sep get no effect. Pooled 2016-25 it is 0.92 at both sites. 2025 is only 0.76-0.77, because August 2025 carried about a fifth of
  that year's load, and August is outside the window. `method_detail.path_a_trial.w.by_year` has every year.

**Path (b), river-model sensitivity (no tested skill).** `D_b(t) = 1 - cf/base` for the v1 GBM median simulation, where
cf has the causal bare share cut by X (relative) on Oct 15-May 31 (`river.perturb_cover`, all cover features recomputed).
- The spread is a per-draw multiplier k. It combines the Bayesian-bootstrap refits over training years (sensitivity.json
  5-95%, as a split normal, interpolated in X between 10/25/50%) with the SD of the median, p10 and p90 models' responses.
- **The bare-soil features add no tested skill.** Leave-one-year-out ln-RMSE improves by only 0.002 (Des Moines) and
  0.005 (Raccoon) when they are included (sensitivity.json `diagnostics.cv_rmse_log_gain_from_bare_features`). Yet at
  25% this path cuts the annual load 8.7% at the Des Moines River against 2.0% at the Raccoon. The size of the effect is
  not something the river data can confirm.
- sensitivity.json also has a v2 bootstrap block, but the modeler keeps the driver-only v1 for relative what-ifs, so the
  learned path stays on v1 even when the chart shows v2.

**Blend and headline (decision after review).** Equal-weight MIXTURE: half of the Monte Carlo draws use the trial-prior
path, half the river-model path (`MIX_TRIAL` in m07). **The mixture stays the headline, and "trials only" is exported
next to it for every year and level** (`by_year.<y>.levels[].trials_only.avoided`, same p50/lo/hi keys), so the UI
can show both. This is stated in `scenarios.json → headline` and in `method`.
- The mixture's plant-day result leans on the unvalidated river-model half: 2025 at 25% avoids 17 (7-33) real plant days
  river-model only, 10 (2-36) trials only, 16 (3-34) mixture (`headline.river_model_dominates_plant_days: true`). The
  method text says so and calls "trials only" the conservative, trial-anchored figure. Inverse-variance weights are still computed and reported (table below, `weights` in
scenarios.json) only as a diagnostic; they were rejected because the learned path's narrow bootstrap spread omits its
known identification problem, which would have put 93-97% of the Raccoon weight on the weaker evidence.
- 4,000 draws, with common random numbers across levels and years, so results are monotone in X within a draw.
- Reported: p50 and p10-p90 ("8 in 10"). The `avoided` blocks are differences computed inside each draw.

| annual load cut, % (p50, p10-p90) | X | trial (a) | learned (b) | inverse-variance blend (diagnostic, not used) | IV weight on trials |
|---|---|---|---|---|---|
| Raccoon | 10% | 1.9 (0.4-4.1) | 0.8 (0.5-1.1) | 0.9 (0.5-1.1) | 0.03 |
| Raccoon | 25% | 4.8 (1.1-10.3) | 2.0 (1.3-2.7) | 2.1 (1.4-2.7) | 0.02 |
| Raccoon | 50% | 9.5 (2.1-20.7) | 5.9 (4.0-8.2) | 6.2 (4.3-8.4) | 0.05 |
| Des Moines | 10% | 1.9 (0.4-4.2) | 4.7 (3.0-6.5) | 3.4 (2.2-4.8) | 0.49 |
| Des Moines | 25% | 4.8 (1.1-10.4) | 8.7 (5.7-12.2) | 7.6 (5.2-10.4) | 0.33 |
| Des Moines | 50% | 9.6 (2.1-20.8) | 15.8 (11.0-20.9) | 14.7 (10.5-19.2) | 0.23 |

**Read this before using the blend.** The trial prior's spread is wide: an SD of 26 points on a mean of 28. The learned
path's bootstrap spread is narrow, so inverse-variance weighting puts 95-98% of the Raccoon weight on the learned path.
- That spread does **not** include the identification problem. The modeler documents that the bare-share effect is
  weakly identified: past cover variation was mostly seasonal, and the perturbation leaves the training range.
- The paths happen to agree on 2025 Raccoon days above 10 at 25% adoption: trials alone give 9 (1-21), the learned
  model alone 7 (3-9). The paths disagree on size at the Raccoon: the learned annual load cut is about half the trial
  one. At the Des Moines River they disagree the other way: the learned cut is about twice the trial one, which is why
  the learned path drives Des Moines days and plant days.
- Path-only results are in `scenarios.json → method_detail.path_only_avoided` (2025 and 2026, every level); trials-only
  is also on every level of every year (`levels[].trials_only`).
- 2025 at 25% adoption: mixture days > 10 avoided 7 (2-16), plant days 16 (3-34), operating $234k (47k-507k), ban days
  23 (9-31); trials only 9 (1-21), 10 (2-36), $157k (29k-534k), 17 (2-28).

## 3. Operating-rule proxies (the utility's rules are not public)
### Removal plant
**Rule family.** The plant runs when the 7-day trailing mean (≥ 4 measured days) of an aggregate of the two rivers is
above T. The aggregate is the higher river, the average or the lower river.
- The aggregate and T were chosen on 2025 only, by daily F1 against the reported run days (10-18 Apr and 28 Apr-8 Aug,
  112 days; fact `plant_days_2025`). The run windows are checked against the fact total at run time.
- **Chosen: the average of the two rivers > 10.2 mg/L**, which sits close to the 10 mg/L limit.
- **Threshold uncertainty.** The 2025 fit is flat for T = 9.4-10.2 (F1 within 0.025 of the best), so the Monte Carlo
  draws T from that set.

| | proxy days | reported | hits | false alarms | misses | daily F1 |
|---|---|---|---|---|---|---|
| 2025 fit (T = 10.2) | 106 | 112 | 102 | 4 | 10 | 0.94 |
| **2026 test, Jan-Jul, no refit** | **157** | **193** | 157 | 0 | 36 | **0.90** |
| 2026 Aug-Nov (unverified) | 23 | 0 reported | | | | |

**Plant days counted in the scenarios (rule changed after review).** In years with reported run dates (2025: 10-18 Apr
and 28 Apr-8 Aug; 2026: 6 Jan-2 Mar and 9 Mar-23 Jul; facts `plant_days_2025`, `plant_days_2026`), a plant day counts
only if the proxy says "on" **and** the real plant ran (`pl & truth` in m07). An avoided plant day is therefore a real run
day that the scenario switches off. Before the fix, avoided days came from proxy-on days alone: in 2025 only about 15 of
23 avoided days fell inside the real run, and in 2026 about 4 of 19 were Aug-Nov days when the plant was off.
- Baseline counted plant days: 2025 106 (102-112) of 112 reported; 2026 167 (158-173) of 193.
- 2016-2024 have no reported run dates, so those years still count proxy days (`plant_days_basis` on each level).
- The proxy-only counts stay in the output as a diagnostic (`plant_days_proxy`, `avoided.plant_days_proxy`): 2025 at 25%,
  24 (5-40) proxy-only against 16 (3-34) counted.

**2026 test, honestly.**
- The proxy never ran the plant when the utility did not, but it missed 36 run days. The misses are shoulder days when
  the average was just under 10.2: 6-12 Jan (except 8 Jan), 16 Feb-2 Mar, 9-12 Mar, 3-9 Jul and 20-23 Jul.
- So in 2026 the utility ran the plant earlier and longer than a 2025-fitted rule predicts. Lower thresholds in the
  drawn set (9.4-9.9) fit 2026 better.
- The proxy also turns the plant on for 23 days in Oct-Nov 2026 (14 Oct-2 Nov and 11-13 Nov). No fall restart had been reported when facts were
  checked, so those days are probably false alarms.
- Other aggregates, for transparency: the "higher river" rule (T = 10.3) scored 0.91 on 2025 and 0.93 on 2026. The
  "lower river" rule (T = 9.1) scored 0.91 and 0.91. See `thresholds.calibration.plant.alternatives`.

### Lawn-watering ban
**Rule (not fitted).** In the Jun-Aug demand season, a ban is on when the plant proxy is on and BOTH rivers' 7-day means
are above 10 mg/L.
- The 10 mg/L comes from CIWW's 2025 lift rule: at least one source must read 10 mg/L or less (fact `ban_lift_rule`).
- Ban days are the all-customer Stage III window: 2025 12 Jun-7 Aug, 56 days; 2026 8 Jun-20 Jul, 42 days. Homes were
  released earlier: 40 days in 2025 and 23 in 2026.

| | proxy days | reported (all / homes) | dates | F1 (all) |
|---|---|---|---|---|
| 2025 fit | 66 | 56 / 40 | 1 Jun-8 Aug (real 12 Jun-7 Aug) | 0.87 |
| **2026 test** | **40** | 42 / 23 | 1 Jun-19 Jul (real 8 Jun-20 Jul) | **0.81** |

- **The proxy starts too early.** It begins on 1 Jun in both years, so it overcounts by about 10 days in 2025.
- **A fitted start threshold over-fits.** A start trigger fitted to 2025 (lower river > 13.25 mg/L) matches 2025 almost
  exactly: 58 days, F1 0.98. In 2026 it finds **no ban at all**, because the 2026 ban came at lower nitrate.
- A ban also depends on demand (heat; lawn watering is up to ~40% of summer demand), treatment capacity and the
  infiltration gallery, which the proxy cannot see. **Treat ban-day changes as indicative.**

### Cost
- Plant days x operating cost per day, ~ U[$14,286, $16,000]. The low end is 2025 O&M ($1.6M) / 112 days; the high end
  is full capacity (facts `plant_om_cost_2025_usd`, `plant_days_2025`, `plant_cost_per_day_usd`).
- **The range is kept because no source gives a partial-operation daily cost.** The CIWW page (re-read 2026-11-15) says
  only that full capacity costs about $16,000 a day; the ~$4k/day lower bound in `facts.json → plant_cost_per_day_usd.range`
  has no quote behind it and is not used.
- Lower-rate sensitivity: Q1-2026 O&M ($660k, `plant_om_cost_2026_q1_usd`) over the 79 Q1-2026 run days is about
  $8,354 per run day (winter, partial operation). `avoided.cost_usd_q1_2026_rate` uses it: 2025 at 25%, $134k (25k-284k)
  mixture, $84k (17k-301k) trials only.
- Capital ($0.6M in 2025; the ~$40M expansion) is not avoided in the short run.
- People served: >600,000 (`water_people_served`).

## 4. Results, 2025 and 2026 replays (avoided vs today; p50 and 8-in-10 range)
In 2025 the river was measured above 10 mg/L on 115 days at the Raccoon and 105 at Des Moines. The plant ran 112 days
(proxy median 120, of which 106 inside the real run) and the ban lasted 56 days (proxy 68). The two rivers carried a load
of 55,300 t N.

Regenerated from web/data/scenarios.json (run 2026-11-15 00:38 UTC). "Mixture" is the headline; "trials only" puts every
draw on the trial path. Plant days count real run days only (§3).

| year | X | basis | days > 10, Raccoon | days > 10, Des Moines | plant days (real run days) | plant O&M $ | ban days (indicative) | load, t N | N kept, lb |
|---|---|---|---|---|---|---|---|---|---|
| 2025 | 10% | mixture | 2 (0-4) | 8 (0-15) | 3 (1-10) | $48k (15k-154k) | 9 (1-13) | 1,170 (376-1,781) | 2.6M (0.8-3.9M) |
| 2025 | 10% | trials only | 2 (0-5) | 5 (0-13) | 4 (0-10) | $59k (0k-149k) | 9 (0-13) | 876 (195-1,908) | 1.9M (0.4-4.2M) |
| 2025 | 25% | **mixture** | **7 (2-16)** | **21 (5-36)** | **16 (3-34)** | **$234k (47k-507k)** | **23 (9-31)** | **2,966 (951-4,508)** | **6.5M (2.1-9.9M)** |
| 2025 | 25% | trials only | 9 (1-21) | 13 (2-28) | 10 (2-36) | $157k (29k-534k) | 17 (2-28) | 2,191 (487-4,769) | 4.8M (1.1-10.5M) |
| 2025 | 50% | mixture | 16 (5-43) | 43 (13-67) | 35 (9-60) | $528k (134k-918k) | 32 (13-44) | 5,981 (1,906-8,691) | 13.2M (4.2-19.2M) |
| 2025 | 50% | trials only | 18 (2-60) | 24 (5-66) | 31 (4-68) | $470k (62k-1,035k) | 28 (9-50) | 4,382 (974-9,538) | 9.7M (2.1-21.0M) |
| 2026 | 10% | mixture | 3 (0-8) | 11 (0-18) | 6 (1-11) | $86k (15k-170k) | 1 (0-7) | 1,126 (463-1,936) | 2.5M (1.0-4.3M) |
| 2026 | 10% | trials only | 4 (0-10) | 11 (0-19) | 4 (1-13) | $63k (14k-198k) | 1 (0-11) | 1,111 (247-2,419) | 2.5M (0.5-5.3M) |
| 2026 | 25% | **mixture** | **5 (4-22)** | **30 (11-56)** | **14 (4-29)** | **$209k (64k-444k)** | **16 (1-26)** | **2,856 (1,185-4,843)** | **6.3M (2.6-10.7M)** |
| 2026 | 25% | trials only | 12 (1-30) | 21 (7-71) | 14 (2-37) | $218k (29k-564k) | 12 (0-29) | 2,779 (618-6,048) | 6.1M (1.4-13.3M) |
| 2026 | 50% | mixture | 15 (6-81) | 83 (19-137) | 47 (10-101) | $714k (147k-1,546k) | 40 (11-40) | 5,858 (2,417-9,667) | 12.9M (5.3-21.3M) |
| 2026 | 50% | trials only | 27 (4-116) | 60 (11-149) | 33 (5-135) | $500k (73k-2,032k) | 26 (1-40) | 5,557 (1,236-12,097) | 12.2M (2.7-26.7M) |

2026 is a partial year (data to 2026-11-13); its plant days stop at the reported 23 Jul shutdown, so Aug-Nov proxy days
never count. Previous run (proxy-on plant days): 2025 at 25% plant days 23 (5-41), $350k; 2026 19 (7-51), $282k.

**Reading.**
- The Raccoon sat far above 10 for long stretches in 2025-26, so a 2-3% load cut flips few of its days.
- Plant and ban days respond more, because the proxy rules use the average or the lower of the two rivers. Those
  hovered at 10-11 mg/L in late spring and summer, and the Des Moines River responds more in the river-model path
  (which has no tested skill; compare the trials-only rows).
- These are threshold effects of proxy rules. The ban numbers are the least certain.
- "N kept" is nitrate that would have reached the two gauges; on-farm retention is larger.

## 5. Web export (m08), web/data
| file | content / notes |
|---|---|
| `river_series.json` | daily 2016-01-01 to latest; obs, q_cfs, p10/p50/p90 of the display model per site (`sites[s].model`), reservoir_p50, `provisional_from`; split dates (live end = last date) |
| `validation.json` | `{display_model, splits, sites{<site>{name, by_split{train,test,live}{gbm, reservoir, climatology, persistence_7d, persistence_14d, gbm_v2?}, test_by_year, crisis_2025, live_2026, level_ratio_obs_over_model, v2?}}, lines[], crisis_2025.text, outlook_skill}`. Train `gbm` is the leave-one-year-out CV, not the in-sample fit. `lines` includes the honest 2025 miss and its explanation, plus a v2 line when v2 exists |
| `outlook.json` | model/out/outlook.json, rounded |
| `scenarios.json` | contract + `x_definition`, `hls_winter_cover_pct` ({lo, hi, by_year}), `headline`, `method_detail` (incl. `plant_day_rule`, `path_only_avoided` at every level), `thresholds.calibration`, `replays{2025, 2026}` (+ `plant_on_reported`), `levels[].avoided`, `levels[].trials_only.avoided`, `plant_days_proxy`, `days_over10_dm`, `load_tN_*`, `caveats` |
| `fields.geojson`, `field_detail/<huc12>.json` (10 files), `field_index.json` | copies of fields_model output (detail rounded); split files only |
| `strategies.json` | copy, rounded |
| `huc12.geojson` | existing outlines and props + `huc12_props.json`: leak_index, share_of_basin_leak, rank, row_crop_share, poorly_drained_share, bare_days_wet, in_focus, lbN_ac_yr, share_of_basin_leak_recent, n_in_basin |
| `facts.json` | `{facts:{<id>:{value, unit, label, source, url, verification, verified, range, quote, ...}}, aliases}`. Unverified facts are dropped. Alias keys: people_served, plant_days_<Y>, plant_cost_2025_usd, ban_days_<Y>, fert_price_usd_lb_N (+ plant_om_cost_2025_usd, plant_cost_per_day_usd, mcl_mgL). There is no `plant_cost_2026_usd` because no full-year figure exists |
| `meta.json` | data_through (nwis, power, modis, hls, cdl, model_series), 13 sources with nasa flags and roles, caveats, file sizes |

Total 7.1 MB (limit 15 MB). Every file parses, and `python3 -m http.server` serves them, including the directory
listing the loader reads. m08 never writes basins/sites/rivers/counties/places.

**Display model.** metrics.json `display_model` may be a string or the v2 run's per-site dict
(`{sites:{<site>:{model}}}`). For a v2 site, `river_series` takes p10/p50/p90 from `model/out/v2/river_daily_v2.parquet`.
validation adds `gbm_v2` (train = its LOYO CV), the strict check and the blind 2013 test. Default is v1.
In the final run (23:49 UTC), the modeler's rule picked **v2 at both sites**. The chart therefore shows v2, the
validation lines label the v1 numbers as v1, and the scenario numbers are unchanged, because they use observed
series and the v1 learned path.

## 6. Limitations
1. **Legacy nitrate.** Soil and groundwater nitrate mean a field change takes more than one season to show in the river.
   Results describe a fully developed effect, replayed on that year's weather and river.
2. **Current adoption.** About 17% of Iowa corn+soy acres already have cover (`iowa_cover_share_pct`, secondary,
   statewide). X is a share of all upstream corn/soy acres added on top, so 25% means about 42% covered and 50% about
   two-thirds. Satellite (HLS) detects winter cover on only 0.8-4.2% of fields a year against that ~17%: it sees only
   cover that has grown enough by late fall or early spring, so it is a lower bound (many covers are drilled late or
   stay small).
3. **Typical adopters.** Adopters are assumed to be typical fields. Targeting leaky tile-drained fields would do more;
   poor rye establishment would do less. Cover is assumed living and effective all Oct-May; real fall establishment is
   slower.
4. **Weak evidence on size.** Trial efficiencies are drainage-concentration means with large SDs. The river-model
   response is weakly identified, its bare-soil features add no tested LOYO skill, and its bootstrap spread is too
   narrow (§2). It drives most of the mixture's plant-day effect; trials-only is shown alongside.
5. **Proxy rules.** The rules are proxies. The plant proxy misses shoulder days (2026 test); the ban proxy starts early
   and cannot see demand or capacity.
6. **Cost.** Only operating cost is counted, and per-day cost on shoulder days may be lower than the range used (no
   source gives a partial-operation cost; Q1-2026 averaged about $8.4k per run day, used as a sensitivity).
7. **Flow.** Flow is held fixed; cover crops can slightly reduce spring drainage volume, which is not counted.
8. **Data.** 2026 is partial and its nitrate data are partly provisional. Des Moines nitrate is missing 3 Jan-2 Mar 2025 (except
   11-12 Jan) plus scattered fall days; it is gap-filled for loads only, and the plant rule uses the Raccoon alone there.
