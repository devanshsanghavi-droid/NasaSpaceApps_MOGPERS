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

Numbers below are from the run of 2026-11-14 ~23:40 UTC (NWIS through 2026-11-13; v1 river model refit at 23:31-23:34).

## 1. The question and the lever
"What if X% more of the upstream row-crop acres (both intake basins: Raccoon at Van Meter 05484500 and Des Moines River
at 2nd Ave 05482000) grew a cereal-rye-type living cover from October to May, on top of current practice?"
X = 0, 5, ..., 50. Results for every calendar year 2016-2026 (2026 partial, through Nov 13); replays for 2025 and 2026.

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

**Path (b), learned model.** `D_b(t) = 1 - cf/base` for the v1 GBM median simulation, where cf has the causal bare share
cut by X (relative) on Oct 15-May 31 (`river.perturb_cover`, all cover features recomputed).
- The spread is a per-draw multiplier k. It combines the bootstrap refits over training years (sensitivity.json 5-95%,
  as a split normal, interpolated in X between 10/25/50%) with the SD of the median, p10 and p90 models' responses.
  These are the uncertainty sources sensitivity.json lists.
- The v2 run publishes no bootstrap sensitivity, and the modeler keeps the driver-only v1 for relative what-ifs, so the
  learned path stays on v1 even when the chart shows v2.

**Blend (orchestrator decision, final).** Equal-weight MIXTURE: half of the Monte Carlo draws use the trial-prior path,
half the learned-model path (`MIX_TRIAL` in m07). The headline range therefore spans both lines of evidence and stays
anchored to Iowa trials. Inverse-variance weights are still computed and reported (table below, `weights` in
scenarios.json) only as a diagnostic; they were rejected because the learned path's narrow bootstrap spread omits its
known identification problem, which would have put 93-97% of the Raccoon weight on the weaker evidence.
- 4,000 draws, with common random numbers across levels and years, so results are monotone in X within a draw.
- Reported: p50 and p10-p90 ("8 in 10"). The `avoided` blocks are differences computed inside each draw.

| annual load cut, % (p50, p10-p90) | X | trial (a) | learned (b) | inverse-variance blend (diagnostic, not used) | IV weight on trials |
|---|---|---|---|---|---|
| Raccoon | 10% | 1.9 (0.4-4.1) | 0.8 (0.5-1.2) | 0.9 (0.5-1.3) | 0.04 |
| Raccoon | 25% | 4.8 (1.1-10.3) | 2.1 (1.2-2.9) | 2.2 (1.3-3.0) | 0.03 |
| Raccoon | 50% | 9.5 (2.1-20.7) | 5.9 (3.6-8.7) | 6.3 (4.0-8.9) | 0.07 |
| Des Moines | 10% | 1.9 (0.4-4.2) | 4.7 (2.6-6.8) | 3.2 (2.0-4.7) | 0.56 |
| Des Moines | 25% | 4.8 (1.1-10.4) | 8.6 (5.2-12.3) | 7.4 (4.8-10.3) | 0.37 |
| Des Moines | 50% | 9.6 (2.1-20.8) | 16.0 (10.6-21.9) | 14.5 (10.0-19.5) | 0.27 |

**Read this before using the blend.** The trial prior's spread is wide: an SD of 26 points on a mean of 28. The learned
path's bootstrap spread is narrow, so inverse-variance weighting puts 93-97% of the Raccoon weight on the learned path.
- That spread does **not** include the identification problem. The modeler documents that the bare-share effect is
  weakly identified: past cover variation was mostly seasonal, and the perturbation leaves the training range.
- The paths happen to agree on 2025 days above 10 at 25% adoption: trials alone give 9 (1-21), the learned model alone
  7 (3-11). The paths disagree on size at the Raccoon: the learned annual load cut is about half the trial one. At the
  Des Moines River they disagree the other way: the learned cut is about twice the trial one.
- Path-only results are in `scenarios.json → method_detail.path_only_avoided` (2025 and 2026, X = 10/25/50).
- The equal-weight mixture is what the app shows. 2025 at 25% adoption (mixture): days > 10 avoided 8 (2-16), plant
  days 23 (5-41), operating $ 350k (73k-620k), ban days 23 (9-31).

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
- Capital ($0.6M in 2025; the ~$40M expansion) is not avoided in the short run.
- Avoided days are shoulder days, when partial operation can cost less (facts: as low as ~$4k/day), so the $ range may be
  high.
- People served: >600,000 (`water_people_served`).

## 4. Results, 2025 replay (avoided vs today; p50 and 8-in-10 range)
In 2025 the river was measured above 10 mg/L on 115 days at the Raccoon and 105 at Des Moines. The plant ran 112 days
(proxy median 120) and the ban lasted 56 days (proxy 68). The two rivers carried a load of 55,300 t N.

| X | days > 10, Raccoon | days > 10, Des Moines | plant days | plant O&M $ | ban days (indicative) | load, t N | N kept, lb |
|---|---|---|---|---|---|---|---|
| 10% | 2 (1-2) | 8 (4-10) | 6 (3-13) | $89k (43k-191k) | 8 (5-10) | 1,060 (710-1,490) | 2.3M (1.6-3.3M) |
| 25% | **7 (3-11)** | 22 (12-29) | **24 (10-36)** | **$360k (151k-548k)** | **23 (16-30)** | 2,890 (2,020-3,800) | 6.4M (4.5-8.4M) |
| 50% | 17 (7-30) | 46 (27-65) | 46 (27-62) | $695k (404k-941k) | 33 (29-42) | 6,040 (4,420-7,760) | 13.3M (9.7-17.1M) |

2026 at 25%, partial year: 5 (5-5) fewer Raccoon days above 10, 30 (16-49) at Des Moines, 17 (11-27) plant days,
$263k (165k-412k) and 15 (12-25) ban days.

**Reading.**
- The Raccoon sat far above 10 for long stretches in 2025-26, so a 2-3% load cut flips few of its days.
- Plant and ban days respond more, because the proxy rules use the average or the lower of the two rivers. Those
  hovered at 10-11 mg/L in late spring and summer, and the Des Moines River responds more in the learned path.
- These are threshold effects of proxy rules. The ban numbers are the least certain.
- "N kept" is nitrate that would have reached the two gauges; on-farm retention is larger.

## 5. Web export (m08), web/data
| file | content / notes |
|---|---|
| `river_series.json` | daily 2016-01-01 to latest; obs, q_cfs, p10/p50/p90 of the display model per site (`sites[s].model`), reservoir_p50, `provisional_from`; split dates (live end = last date) |
| `validation.json` | `{display_model, splits, sites{<site>{name, by_split{train,test,live}{gbm, reservoir, climatology, persistence_7d, persistence_14d, gbm_v2?}, test_by_year, crisis_2025, live_2026, level_ratio_obs_over_model, v2?}}, lines[], crisis_2025.text, outlook_skill}`. Train `gbm` is the leave-one-year-out CV, not the in-sample fit. `lines` includes the honest 2025 miss and its explanation, plus a v2 line when v2 exists |
| `outlook.json` | model/out/outlook.json, rounded |
| `scenarios.json` | contract + `method_detail`, `thresholds.calibration`, `replays{2025, 2026}`, `levels[].avoided`, `days_over10_dm`, `load_tN_*`, `caveats` |
| `fields.geojson`, `field_detail/<huc12>.json` (10 files), `field_index.json` | copies of fields_model output (detail rounded); split files only |
| `strategies.json` | copy, rounded |
| `huc12.geojson` | existing outlines and props + `huc12_props.json`: leak_index, share_of_basin_leak, rank, row_crop_share, poorly_drained_share, bare_days_wet, in_focus, lbN_ac_yr, share_of_basin_leak_recent, n_in_basin |
| `facts.json` | `{facts:{<id>:{value, unit, label, source, url, verification, verified, range, quote, ...}}, aliases}`. Unverified facts are dropped. Alias keys: people_served, plant_days_<Y>, plant_cost_2025_usd, ban_days_<Y>, fert_price_usd_lb_N (+ plant_om_cost_2025_usd, plant_cost_per_day_usd, mcl_mgL). There is no `plant_cost_2026_usd` because no full-year figure exists |
| `meta.json` | data_through (nwis, power, modis, hls, cdl, model_series), 13 sources with nasa flags and roles, caveats, file sizes |

Total 7.0 MB (limit 15 MB). Every file parses, and `python3 -m http.server` serves them, including the directory
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
   statewide). X is additional acres, so 50% means roughly two-thirds of acres covered.
3. **Typical adopters.** Adopters are assumed to be typical fields. Targeting leaky tile-drained fields would do more;
   poor rye establishment would do less. Cover is assumed living and effective all Oct-May; real fall establishment is
   slower.
4. **Weak evidence on size.** Trial efficiencies are drainage-concentration means with large SDs. The learned river
   response is weakly identified, and its bootstrap spread is too narrow (§2).
5. **Proxy rules.** The rules are proxies. The plant proxy misses shoulder days (2026 test); the ban proxy starts early
   and cannot see demand or capacity.
6. **Cost.** Only operating cost is counted, and per-day cost on shoulder days may be lower than the range used.
7. **Flow.** Flow is held fixed; cover crops can slightly reduce spring drainage volume, which is not counted.
8. **Data.** 2026 is partial and its nitrate data are partly provisional. Des Moines nitrate is missing 3 Jan-2 Mar 2025 (except
   11-12 Jan) plus scattered fall days; it is gap-filled for loads only, and the plant rule uses the Raccoon alone there.
