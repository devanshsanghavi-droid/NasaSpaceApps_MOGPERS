# Module `model`: river nitrate simulation, validation, bare-soil sensitivity, 14-day outlook

Scripts, run from `apps/field-to-faucet/`. Each is re-runnable end-to-end; LightGBM runs single-threaded.

```
# v1 (pre-registered)
python3 model/m01_features.py        # ~2 s    -> out/features.parquet
python3 model/m02_river_model.py     # ~4 min  -> out/river_daily.parquet, out/metrics.json, out/models/
python3 model/m03_sensitivity.py     # ~30 s   -> out/sensitivity.json (top level = v1)
python3 model/m04_outlook.py         # ~2 min  -> out/outlook.json, metrics.json['outlook']

# v2 (legacy-N, post-hoc)
python3 model/m06_history.py         # ~6 min cold -> pre-2016 NWIS/POWER/MODIS/CDL in out/ (cache: model/cache/)
python3 model/m07_features_v2.py     # ~10 s   -> out/features_v2.parquet
python3 model/m08_v2.py              # ~15 min -> out/v2/river_daily_v2.parquet, out/models_v2/,
                                     #            metrics.json['v2', 'display_model']
python3 model/m03_sensitivity.py --v2  #         -> sensitivity.json['v2']

python3 model/m05_figures.py         # -> out/fig_*.png
```

Library modules:
- `featlib.py`: causal features; `load_raw(history=True)` gives the extended v2 record.
- `qgbm.py`: monotone quantile LightGBM.
- `reservoir.py`: conceptual model.
- `river.py`: the API (`model_version='v1'|'v2'`, `level_correct`, `display_version`).

Numbers below are from the run on 2026-11-14, with data through 2026-11-13 (NWIS) and 2026-11-11 (POWER). The run includes the verifier fixes (section 7).

## Bottom line (read this first)
**v1 (pre-registered, drivers only).**
- Test 2023-2025 NSE: Raccoon 0.62, Des Moines 0.56. Climatology scores 0.30 and 0.27; the reservoir model 0.38 and 0.54.
- It misses the 2025 crisis. Raccoon had 115 observed days above 10 mg/L; v1 predicted 6. Des Moines had 105; v1 predicted 10.
- Its out-of-sample annual level error is large: the SD of annual residuals is ≈ 0.3 in ln units. 2025-26 ran ×1.5-2.1.

**v2 (legacy-N, designed after seeing the v1 miss: test and live scores are post-hoc).**
- v2 adds a causal N-carryover store and, for the Raccoon, trains on 2012-2022.
- **Raccoon:**
  - 2025: 83 days above 10 vs 115 observed (v1: 6).
  - Test NSE 0.78, 80% coverage 0.80.
  - 2026 NSE 0.48 (v1 −0.09).
  - **Pre-registered blind 2013 check** (v2 fitted and tuned without 2013): 81 vs 92 observed days, NSE 0.85.
  - But the v1 feature set trained on the same longer record also gets 80 days (NSE 0.79), so most of the 2013 skill comes from the longer record rather than the carryover store.
  - **Strict check** (train 2012-2019, test 2020-2025): ln-RMSE 0.75 for v2 vs 0.99 for the v1 features on the same years.
- **Des Moines:** essentially no gain. 2025 is still 10 of 105 days; test NSE 0.59 vs 0.56; the strict check improves only 1.20 vs 1.25.

**Display rule** (fixed before any v2 2026 metric was computed; v1's 2026 miss was already known; `metrics.json → display_model`):
- Use v2 iff (a) its 2016-2022 LOYO CV is no worse than v1's and (b) it improves the strict check.
- Result: **v2 at both sites** (Raccoon CV 0.519 vs 0.527, strict 0.75 vs 0.99; Des Moines CV 0.463 vs 0.522, strict 1.20 vs 1.25).
- The Des Moines gain is marginal; read Des Moines v2 as "about v1".

**Level-corrected variant** (uses the last 60 days of measured nitrate) for absolute levels:
- 2025 days above 10 mg/L: Raccoon 140 (v2) / 133 (v1) vs 115 observed; Des Moines 114 / 99 vs 105.
- It over-shoots, and it is unstable where model timing is wrong (Des Moines 2026: NSE −1.0).
- Use it only as a level anchor. The driver-only models remain the basis for relative what-ifs.

**Outlook.** It beats persistence in squared error at every lead: test MSE skill +20%/+25% at Raccoon (h7/h14) and +37%/+17% at Des Moines. **It has no probability skill at 14 days** against probabilistic persistence (Brier skill +0.03 Raccoon, −0.04 Des Moines; at 7 days +0.13 and +0.19).

**Bare-soil sensitivity.** It is weakly identified and is a **concentration change conditional on observed flow** (not a load change). Days above 10 mg/L avoided per year at a 25% cut, central model with the 5-95% Bayesian-bootstrap range (mostly in-sample):

| version | Raccoon | Des Moines |
|---|---|---|
| v1 | 3.8 (2.5-11.0) | 10.6 (6.6-18.5) |
| v2 | 11.3 (11.7-21.1) | 5.2 (4.3-12.0) |

The bare-soil features add no tested skill (LOYO ln-RMSE gain 0.002-0.009). Blend with trial priors and show the
trials-only result alongside.

## 1. Features (`m01_features.py` → `features.parquet`; v2: `m07_features_v2.py` → `features_v2.parquet`)
Every feature at day t uses only data from days ≤ t. Weather features are NaN where POWER is missing (latency); they are never computed from partial windows.

| group | features |
|---|---|
| rain (POWER PRECTOTCORR) | `rain_{1,3,7,14,30,60,90,180,365}`; API `api_k85/k95/k98` |
| soil wetness | `gwr`, `gwt`, `gwr_7/30/90/365`, `gwt_7/30` |
| wet rain | `wetrain_{7,30,90}` = Σ P·GWETROOT |
| snow | `melt_{7,30}` (−ΔSNODP), `snodp` |
| temperature | `t2m_7/30`, `gdd5_mar1` |
| cover (MODIS, causal) | `bare`, `bare_30/90/180`, `living` = 1 − bare, `living_30` |
| bare × wet | `barewet_{30,90}` = Σ bare·P·GWETROOT |
| crops (CDL) | `corn_y`, `corn_prev` |
| flow (observed) | `logq`, `logq_7/30`, `dlogq`, `dlogq_7` |
| season | `doy_sin`, `doy_cos` |
| **v2 carryover** | `ncarry_k<k>`, `nflush30_k<k>`, `nflush90_k<k>`, `prior_gs_rain` (below) |
| target | ln(max(no3, 0.05)). 55 approved 0.0 mg/L days are floored at 0.05 mg/L, not dropped. Nitrate is never a simulation input |

**CDL caveat.** The year-y CDL is published early in year y+1, so `corn_y` is not known in real time during year y. As a year-constant feature it can also act as a year proxy. v1's CV picked the CDL group at Raccoon. In 2026, the 2025 values are reused.

**Causal cover.**
- Features use the modis module's `bare_share_asof` / `age_days` / `asof_src`: the latest composite whose 16-day window ended at least 3 days before t.
- The Jul-Nov 2025 MODIS gap is filled from HLS quantile-mapped to MODIS (`asof_src='hls'`).
- When `age_days > 24`, the last anomaly against the 2016-2022 day-of-year climatology decays toward that climatology (e-folding 30 days).
- Before 2015-07 (v2 only), the same as-of rule runs on MODIS 13Q1 composites from 2011-07 that `m06` fetched with p09's own code.
- The non-causal centred series is kept only as `bare_centred_diag`.
- All numbers use the HLS-filled as-of series. No before/after comparison with the earlier interpolated cover is claimed.

**v2 carryover store (Option A, causal):**
- S_t = S_{t−1}·exp(−D_t/k) + I_t, with drainage D = P·GWETROOT² (mm).
- Input I = corn share × a spring pulse (Apr 10-May 31, 1 unit per year).
- Flush F_t = S_{t−1}(1 − exp(−D_t/k)), summed over 30 and 90 days.
- `prior_gs_rain` = Apr-Sep rain of the latest completed season.
- Drought years drain little, so the store builds up (2012-14, 2021-25 in the series) and is flushed when soils get wet again.
- Monotone constraints: carryover and flush (+), prior-season rain (−).
- k ∈ {50, 150, 400, 1000} mm and the prior-rain option are chosen by LOYO CV inside the training years only.
- The store does not depend on cover, so in v2, cover acts only through the bare-share features.

**v2 extended record** (`m06_history.py`; model-owned files, nothing in `data/` is touched):

| source | coverage |
|---|---|
| USGS dv (same code path as p02) | 2011-10..2015-09. Raccoon nitrate from 2012-03-02: 266/236/288/259 days in 2012-15, 2013 max 20.5 mg/L. Des Moines nitrate starts 2016 |
| POWER | 2008-2014 (spin-up), same cells, weights and aggregation as p03 |
| MODIS 13Q1 | 2011-06..2015-06, 380 items, 0 failures |
| CDL corn share (PC `usda-cdl` at 240 m) | 2011-2015. Against the 30 m values for 2016-2021: bias +0.0002, max |error| 0.0011 |

## 2. River simulation models
Splits: **train** 2016-2022 (v2 Raccoon: 2012-2022), **test** 2023-2025, **live** 2026-01-01..2026-11-11.

### v1 (a): monotone quantile GBM
- **Target and quantiles.** ln(no3) at quantiles 0.1, 0.5 and 0.9.
- **Monotone (+)** on `bare*`, `barewet_*`, `gwr*`, `gwt*`.
- **Custom objective.** LightGBM refuses monotone constraints with its built-in quantile objective, so the models use a custom pinball loss (`qgbm.py`). The tails are boosted as offsets from the median model.
- **Hyperparameters** by LOYO CV within 2016-2022:

  | site | leaves | min_child | trees | long memory | CDL | CV ln-RMSE |
  |---|---|---|---|---|---|---|
  | Raccoon | 7 | 150 | 150 | no | yes | 0.527 |
  | Des Moines | 7 | 50 | 800 | no | no | 0.522 |

- **80% band: CQR.** LOYO conformity scores widen the band in log space by 0.40 (Raccoon) and 0.55 (Des Moines).

### v1 (b): two-reservoir conceptual model (`reservoir.py`)

| process | equation |
|---|---|
| snow | rain falls as snow when T ≤ 0; melt 3 mm/°C/day |
| drainage | W ← W + (rain + melt)·GWETROOT^p; D = W/τ_d |
| soil N pool | S ← S + M + Fert − U − L − d·S |
| mineralization | M = 1.07^(T−20) for T > 0 |
| fertilizer | spring pulse plus fraction ff in Nov, scaled by corn share |
| uptake | U = u·living·GWETROOT·f(T)·S |
| leaching | L = k·S·D |
| river store | R ← R + L − R/τ_r |
| concentration | C = c0 + a·(R/τ_r)/(Q/Q_med)^β |

- Fitted on ln C over 2016-2022 (soft-L1, 4 starts).
- Several parameters sit at bounds (ff = 0.7, p ≈ 5-6, β = 0), so it is a transparent cross-check only.

### v1 (c): baselines
- Day-of-year climatology (2016-2022).
- Persistence 7 d / 14 d. These use measured nitrate, so they are forecasts, not simulations.

### v2: legacy-N GBM (`m08_v2.py`)
- v1's feature groups per site, plus the carryover features, under the same monotone quantile GBM and CQR.
- **Hyperparameters and k** by LOYO CV over all training years (Raccoon folds 2012-2022):
  - Raccoon: 15 leaves, min_child 150, 800 trees, k = 1000, prior-rain yes. CV 0.592 over all folds, **0.519 over the 2016-22 folds** (v1 0.527).
  - Des Moines: 7 leaves, min_child 50, 800 trees, k = 400, no prior-rain. CV 0.463 (v1 0.522).
  - On 2012-2015, the Raccoon LOYO NSE is 0.67.

### Validation: v1 vs v2
Concentration in mg/L; days with an observation; "> 10" = observed / predicted days; CSI at 10 mg/L. **v2 test/live = post-hoc.**

| site | split | model | NSE | KGE | RMSE | bias | cov80 | > 10 obs / pred | CSI |
|---|---|---|---|---|---|---|---|---|---|
| Raccoon | test 23-25 | v1 GBM | 0.62 | 0.59 | 2.60 | −1.40 | 0.66 | 189 / 64 | 0.32 |
| Raccoon | test 23-25 | **v2 GBM** | **0.78** | 0.87 | 1.96 | −0.24 | 0.80 | 189 / 154 | 0.52 |
| Raccoon | test 23-25 | reservoir | 0.38 | 0.49 | 3.33 | −1.46 | 0.55 | 189 / 42 | 0.22 |
| Raccoon | test 23-25 | climatology | 0.30 | 0.41 | 3.52 | −0.13 | 0.65 | 189 / 42 | 0.14 |
| Raccoon | test 23-25 | persistence 7 d / 14 d | 0.77 / 0.66 | 0.88 / 0.83 | 2.01 / 2.41 | – | – | – | 0.61 / 0.53 |
| Raccoon | test 23-25 | level-corrected v2 (uses obs) | 0.79 | 0.88 | 1.95 | – | 0.85 | 189 / 214 | 0.67 |
| Raccoon | live 2026 | v1 GBM | −0.09 | 0.43 | 4.34 | −3.51 | 0.60 | 174 / 7 | 0.04 |
| Raccoon | live 2026 | **v2 GBM** | **0.48** | 0.72 | 3.00 | −1.44 | 0.89 | 174 / 121 | 0.62 |
| Raccoon | live 2026 | climatology | −0.49 | 0.38 | 5.05 | −4.08 | 0.51 | 176 / 14 | 0.07 |
| Raccoon | live 2026 | level-corrected v2 | 0.46 | 0.70 | 3.06 | – | 0.98 | 174 / 172 | 0.83 |
| Des Moines | test 23-25 | v1 GBM | 0.56 | 0.54 | 2.97 | −1.48 | 0.64 | 166 / 25 | 0.12 |
| Des Moines | test 23-25 | v2 GBM | 0.59 | 0.62 | 2.88 | −0.91 | 0.50 | 166 / 22 | 0.07 |
| Des Moines | test 23-25 | reservoir | 0.54 | 0.68 | 3.03 | −0.86 | 0.73 | 166 / 57 | 0.32 |
| Des Moines | test 23-25 | climatology | 0.27 | 0.32 | 3.81 | +0.07 | 0.77 | 166 / 0 | 0 |
| Des Moines | test 23-25 | persistence 7 d / 14 d | 0.90 / 0.80 | 0.95 / 0.90 | 1.43 / 2.04 | – | – | – | 0.72 / 0.60 |
| Des Moines | test 23-25 | level-corrected v2 | 0.81 | 0.87 | 1.96 | – | 0.70 | 166 / 200 | 0.65 |
| Des Moines | live 2026 | v1 GBM | −1.31 | 0.46 | 4.54 | −3.89 | 0.49 | 156 / 17 | 0.11 |
| Des Moines | live 2026 | v2 GBM | −1.18 | 0.47 | 4.41 | −3.80 | 0.44 | 156 / 4 | 0.02 |
| Des Moines | live 2026 | climatology | −1.35 | 0.44 | 4.57 | −4.12 | 0.47 | 158 / 0 | 0 |
| Des Moines | live 2026 | level-corrected v2 | −1.00 | 0.08 | 4.22 | – | 0.77 | 156 / 175 | 0.59 |

Train-period LOYO CV NSE (out-of-fold, 2016-2022):

| site | v1 | v2 |
|---|---|---|
| Raccoon | 0.73 | 0.60 |
| Des Moines | 0.60 | 0.76 |

Raccoon v2 is lower here because its LOYO fits are biased high in some years (bias +0.43).

Test NSE by year:

| site | model | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| Raccoon | v1 | 0.59 | 0.85 | −0.85 |
| Raccoon | v2 | 0.57 | 0.88 | 0.18 |
| Des Moines | v1 | 0.51 | 0.71 | −0.24 |
| Des Moines | v2 | −0.12 | 0.74 | 0.03 |

v2 is worse at Des Moines in 2023.

**2025 crisis** (days above 10 mg/L on observed days):

| site | observed | v1 | v2 | v2 p90 > 10 | reservoir | climatology | level-corrected v2 / v1 | observed peak | v2 peak |
|---|---|---|---|---|---|---|---|---|---|
| Raccoon | 115 (03-26 → still > 10 on 12-31) | 6 | 83 (04-01..10-18) | 280 | 0 | 14 | 140 / 133 | 18.4 (06-07) | 13.7 (08-27) |
| Des Moines | 105 (04-09..08-06) | 10 | 10 | 97 | 0 | 0 | 114 / 99 | 17.0 (06-12) | 12.2 (07-04) |

2026 (live): Raccoon 176 observed vs v1 7 and v2 121; Des Moines 158 vs v1 17 and v2 4.

**Strict check** (`metrics.json → v2.sites.<site>.strict_check`). Train 2012-2019 (Raccoon) or 2016-2019 (Des Moines); ln-RMSE / NSE:

| site | model | 2020-22 | 2023-25 | 2020-25 |
|---|---|---|---|---|
| Raccoon | v2 | 0.65 / 0.65 | 0.83 / 0.60 | **0.75** / 0.64 |
| Raccoon | v1 features, same years | 0.96 / 0.45 | 1.02 / 0.44 | 0.99 / 0.48 |
| Raccoon | v1 features, 2016-19 only | 1.12 / 0.63 | 1.13 / 0.45 | 1.12 / 0.55 |
| Des Moines | v2 | 1.32 / 0.69 | 1.06 / 0.50 | **1.20** / 0.58 |
| Des Moines | v1 features, same years | 1.40 / 0.35 | 1.05 / 0.52 | 1.25 / 0.49 |

Under the strict check, the Raccoon v2 still predicts only 36 of 191 days above 10 in 2023-25. Much of v2's 2025 skill therefore needs the 2020-2022 training years.

**Pre-registered blind 2013 check** (Raccoon; v2 refitted and re-tuned by LOYO without 2013):
- Observed: 92 days above 10, peak 20.5.
- v2: 81 days, NSE 0.85, KGE 0.73, peak 19.4, ln-RMSE 0.97.
- v1 features on the same record: 80 days, NSE 0.79, peak 15.3, ln-RMSE 0.56.
- v2 reproduces 2013, but so does the v1 feature set once 2012/2014/2015 are in training. The carryover store adds little there, and is worse in log error at low concentrations.

### Why v1 misses 2025-26 (a hypothesis, not a finding)
**What we see.**
- Out-of-sample annual residuals (ln obs/pred; `residual_diagnostics`) swing ×0.67-1.36 in the 2016-2022 training years, and 2025-26 sit at the high extreme (×1.68 / 1.53 Raccoon; ×2.07 / 1.83 Des Moines).
- The offset is broad across flow levels in 2025. It does **not** hold in every tercile: the Raccoon 2026 low-flow tercile is ln −0.14.
- 2025 nitrate data are USGS-approved, so the offset is not a provisional-data artifact.

**Candidate explanations.**
- **Legacy soil/groundwater N after the 2020-2023 drought.** Against this as a sole cause:
  - 2023, right after the 2022 drought, ran **low** (×0.89 / ×0.86).
  - The verifier found that the prior-year flow anomaly is only weakly related to annual residuals (r −0.36..−0.56, p 0.12-0.35, n = 9).
  - A fit on 2018-24 predicts only ×1.05 for 2025.
- **Changes in N rates or management** (not observed here).
- **Groundwater nitrate with multi-year residence.**
- **A rain-data shift** (POWER moving to GEOS-IT in the recent period, and possibly a level shift; not checked).

**How v2 bears on it.** v2's post-hoc gain at the Raccoon is consistent with a carryover mechanism. The strict and blind checks show part of it comes from the longer record, and v2 does not help at Des Moines. The hypothesis remains open.

## 3. Bare-soil sensitivity (`m03_sensitivity.py` → `sensitivity.json`; v2 under key `v2`)
**Method.**
- The daily causal bare share is cut by 10/25/50% of its value on Oct 15-May 31, with living share rising to match.
- All cover-derived features are recomputed (`river.perturb_cover`) on the full series (v1 from 2015-01-01; v2 from 2009), and the models re-predict.
- Effects are % changes of the p50, and days above 10 mg/L avoided per year when cf/base is applied to the **observed** series ("obs-anchored").
- Uncertainty: 30 **Bayesian-bootstrap** refits over training years (v1: 2016-2022; v2: Raccoon 2012-2022, Des Moines
  2016-2022). Each refit draws Dirichlet(1) weights per year, scaled to mean 1, and passes them to LightGBM as row
  weights (`qgbm.fit(weight=...)`; the pinball objective multiplies gradient and Hessian by the weight, because LightGBM
  does not apply Dataset weights to a custom objective).
- **Bootstrap fix (2026-11-15, after review).** The earlier bootstrap duplicated the rows of a resampled year. A year drawn
  twice then counted twice against `min_child_samples` (150 for v2), which loosened the trees and inflated the effect:
  the v2 Raccoon range (−18.0..−10.6% at 25%) excluded the deployed model's own −9.6%. With weights and no duplication
  the range is −15.4..−9.7%.
- **The v2 central values still sit at or just outside the edge of the range** (Raccoon 25%: −9.6 vs −15.4..−9.7; Des
  Moines: −5.6 vs −12.4..−6.2). Two further reasons, both stored in sensitivity.json: (1) the deployed model is one seed
  (7), and equal-weight refits on all training years with seeds 100-104 give −9.8..−10.5% (Raccoon) and −5.8..−8.1% (Des
  Moines), so seed 7 sits at the weak end (`gbm.<frac>.seed_spread_all_years`); (2) reweighted refits rarely give a
  smaller effect than the full-data fit, so the bootstrap is skewed toward larger effects. v1 centrals are inside their
  ranges at every level (`bootstrap.central_inside_5_95`).
- **These are concentration changes conditional on the observed flow.** Flow features carry 38-52% of the GBM gain (v1 Raccoon 0.52, Des Moines 0.40; v2 0.41 / 0.38), and cover crops can also cut drainage volume, so these are not load changes.
- Both the central (saved-model) and bootstrap values are mostly in-sample effect sizes, not validated out of sample.

| version | site | bare cut | Δ nitrate in window, central (boot 5-95%) | days > 10 avoided per year, central (boot 5-95%) | 2025 days avoided (central) | d ln C / d bare |
|---|---|---|---|---|---|---|
| v1 | Raccoon | 10 / 25 / 50% | −2.6 / −4.1 / −7.6% (25%: −5.9..−2.9) | 1.2 / **3.8** / 11.7 (25%: 2.5-11.0) | 2 / 7 / 16 | 0.37 → 0.19 |
| v1 | Des Moines | 10 / 25 / 50% | −4.9 / −8.0 / −13.5% (25%: −13.9..−7.2) | 5.4 / **10.6** / 19.7 (25%: 6.6-18.5) | 10 / 27 / 49 | 0.47 → 0.26 |
| v2 | Raccoon | 10 / 25 / 50% | −5.6 / −9.6 / −14.0% (25%: −15.4..−9.7) | 4.9 / **11.3** / 21.3 (25%: 11.7-21.1) | 8 / 13 / 28 | 0.68 → 0.34 |
| v2 | Des Moines | 10 / 25 / 50% | −3.8 / −5.6 / −8.2% (25%: −12.4..−6.2) | 3.7 / **5.2** / 9.7 (25%: 4.3-12.0) | 8 / 15 / 26 | 0.43 → 0.18 |

The reservoir model gives −10 to −37% (Raccoon). Its uptake is learned from summer crops; treat it as an implausible upper bound.

**Identification (weak).**
- 97-98% of bare-share variance is the seasonal cycle. The Oct-May mean varies between seasons with an SD of only 0.019-0.025.
- A 10% cut is already 3.6-4.8 SD, and leaves the training range on 44-63% of window days (87-90% for a 50% cut). Trees extrapolate flat there, so the response saturates.
- Bare-share features improve LOYO ln-RMSE by only 0.002-0.009 (v1: Des Moines 0.002, Raccoon 0.005; v2: 0.009 / 0.002). They add no tested skill.
- The monotone constraint fixes the sign (less bare soil never raises nitrate), not the size.
- The sensitivity differs a lot between v1 and v2 (Raccoon 3.8 vs 11.3 days per year at 25%). That spread is itself a measure of how loosely it is pinned down.
- **The scenario engine must blend it with trial priors and show ranges.**

**API (`model/river.py`, backward-compatible):**
- `load_models(model_version='v1'|'v2')` and `load_features('v1'|'v2')`. A v2 model needs the v2 frame.
- `predict(features_df, site, models=None, model_version=None)` → p10/p50/p90 (CQR band).
- `perturb_cover(features_df, frac, months='oct15-may31'|[months])`.
- `predict_reservoir` (v1 conceptual model).
- `level_correct(pred, obs, dates, window=60, lag=1)` → corrected p10/p50/p90 and `level_factor`.
- `display_version(site)` → the version chosen by the rule.

## 4. 14-day outlook (`m04_outlook.py` → `outlook.json`; unchanged model, v1)
**Model.** LightGBM quantile models (τ 0.05-0.95) of ln(no3[t+h]/no3[t]) for h = 1..14.
- **Inputs:** last nitrate, its 3- and 7-day change, flow through t, season, and drivers as of t−2 (POWER latency).
- **No weather forecast is used.**
- Training rows whose target t+h falls past the split end are dropped (verifier fix).
- **Interval calibration.** The 80% band is widened per lead by a factor calibrated on 2023-2025: 1.2→1.9 (Raccoon), 1.0→1.35 (Des Moines). It covered 0.82 / 0.74 (Raccoon h7 / h14) and 0.79 / 0.81 (Des Moines) on live 2026.

**Skill.** Brier skill is computed against **probabilistic persistence**: the last value ± the training-period distribution of h-day changes. Skill against deterministic persistence is given in brackets and is inflated.

| site | period | lead | RMSE GBM / persistence / climatology of change | MSE skill | Brier skill vs prob. persistence [vs deterministic] | raw cov80 |
|---|---|---|---|---|---|---|
| Raccoon | test 23-25 | 7 d | 1.81 / 2.02 / 1.99 | +20% | +0.13 [+0.34] | 0.61 |
| Raccoon | test 23-25 | 14 d | 2.11 / 2.44 / 2.35 | +25% | **+0.03** [+0.29] | 0.55 |
| Raccoon | live 2026 | 7 d | 1.96 / 2.48 / 2.33 | +38% | +0.21 [+0.38] | 0.61 |
| Raccoon | live 2026 | 14 d | 2.66 / 3.50 / 3.00 | +42% | +0.04 [+0.31] | 0.40 |
| Des Moines | test 23-25 | 7 d | 1.14 / 1.44 / 1.46 | +37% | +0.19 [+0.41] | 0.74 |
| Des Moines | test 23-25 | 14 d | 1.90 / 2.08 / 2.06 | +17% | **−0.04** [+0.28] | 0.72 |
| Des Moines | live 2026 | 7 d | 1.34 / 1.68 / 1.61 | +36% | +0.22 [+0.45] | 0.75 |
| Des Moines | live 2026 | 14 d | 2.01 / 2.24 / 2.05 | +20% | −0.02 [+0.30] | 0.73 |

- **There is no probability skill at 14 days.** Exceedance CSI is about equal to persistence.
- Issued 2026-11-14 from the 11-13 observation:
  - Raccoon: 11.6 → 11.3 mg/L (80% range 9.4-12.5), about 12.5 of 14 days above 10.
  - Des Moines: 11.1 → 9.9 (8.8-12.3), about 11 days.

## 5. Outputs
| file | content |
|---|---|
| `out/features.parquet`, `out/features_v2.parquet` | daily drivers (v2: 2008+ with carryover columns) |
| `out/river_daily.parquet` | v1: site, date, obs, q_cfs, p10, p50, p90, split, reservoir_p50/p10/p90, clim_*, pers7, pers14, gbm_loyo_p50, cover_src, no3_qual |
| `out/v2/river_daily_v2.parquet` | v2: same core columns plus v1_p10/p50/p90, clim_p50, lc_v2_p10/p50/p90, lc_v2_factor, lc_v1_* (Raccoon from 2012) |
| `out/metrics.json` | v1 (top level, as before) + `outlook` + `v2` (per site: hyperparameters, cv_top5, splits{gbm_v2, gbm_v1}, test_by_year, crisis_2025, live_2026, residual_diagnostics, strict_check, blind_2013, level_corrected) + `display_model` {rule, sites} |
| `out/sensitivity.json` | v1 at top level (with flow_conditioning, central_value_note, diagnostics.gain_share) + `v2` |
| `out/outlook.json` | web contract fields + `sites{}` |
| `out/models/`, `out/models_v2/` | boosters (+ `.meta.json`), `config_<site>.json` |
| `out/nwis_2012_2015.parquet`, `out/power_daily_basin_2008_2014.parquet`, `out/cover_basin_8day_2011_2015.parquet`, `out/cdl_basin_year_2011_2015.parquet` | v2 history (model-owned) |
| `out/fig_river_2016_2026.png`, `fig_2025_zoom.png`, `fig_scatter.png`, `fig_outlook.png`, `fig_sensitivity.png`, `fig_v1_v2_2023_2026.png` | figures |

## 6. Limitations
1. **Bare-share identification** is weak and saturating; v1 and v2 disagree. Effects are concentration changes given observed flow, not load changes.
2. **v2 is post-hoc.** It was designed after the v1 2025 miss. Its Des Moines gain is marginal, and the strict check shows its 2025 skill needs 2020-22 data. The year-level error source (legacy N vs management vs groundwater vs rain-data shift) is unresolved.
3. **Saylorville Reservoir** routing is absent: Des Moines is the weakest site in every version.
4. **MODIS** is a 250 m relative index. Jul-Nov 2025 is an HLS fill, and the Raccoon as-of value is 27-30 days stale at issue.
5. **POWER rain** is ~50 km and smooths peaks (OLS slope 0.48 against IMERG on storm days). GEOS-IT is used for the recent period, and a level shift there is unchecked.
6. **NWIS:** about 55% of 2026 data are provisional. Exceedance days are counted on observed days only.
7. **Observed flow is an input** to the simulation and is held fixed in scenarios.
8. **CDL** is year-constant, published in y+1, and a possible year proxy.
9. **Outlook:** no weather forecast; no probability skill at 14 days; 3 calibration years.
10. **Level correction** uses measured nitrate (it is not a simulation), over-shoots, and is unstable when model timing is off (Des Moines 2026).

## 7. Verifier fixes applied in this pass, and v1 numbers that changed
**Fixes.**
1. 55 zero readings are floored at 0.05 mg/L instead of dropped. This **refits v1**: LOYO CV re-selected the hyperparameters (Raccoon 15 → 7 leaves; Des Moines 400 → 800 trees and no longer uses the long-memory or CDL groups).
2. Outlook Brier skill is now against probabilistic persistence, and training rows whose target falls past the split end are dropped.
3. Sensitivity runs on the full series from 2015-01-01 (was 2015-10-01) and states flow conditioning.
4. The legacy-N text is reworded as a hypothesis.
5. v2 k is chosen by LOYO within training years, the blind 2013 check is pre-registered, and v2 scores are labelled post-hoc.

**v1 numbers that changed (before → after):**

| metric | Raccoon | Des Moines |
|---|---|---|
| test NSE | 0.58 → 0.62 | 0.60 → 0.56 |
| test KGE | 0.57 → 0.59 | 0.56 → 0.54 |
| test coverage | 0.63 → 0.66 | 0.63 → 0.64 |
| live NSE | −0.11 → −0.09 | −1.95 → −1.31 |
| live coverage | – | 0.21 → 0.49 |
| 2025 days > 10 (v1) | 7 → 6 | 10 → 10 |
| 2026 days > 10 (v1) | 8 → 7 | 0 → 17 |
| LOYO CV ln-RMSE | 0.517 → 0.527 | 0.490 → 0.522 |
| sensitivity, central days avoided per year at 25% | 4.7 → 3.8 | 5.3 → 10.6 |
| sensitivity, bootstrap at 25% | 6.4 (2.9-11.3) → 4.6 (1.6-9.9) [→ 5.6 (2.5-11.0) Bayesian bootstrap, 2026-11-15] | 5.8 (3.5-12.2) → 10.5 (6.7-18.9) [→ 11.4 (6.6-18.5)] |
| outlook MSE skill, test h7 / h14 | +19/+24% → +20/+25% | +39/+18% → +37/+17% |
| outlook Brier skill, test h7 / h14 | +0.33/+0.29 (deterministic baseline) → +0.13/+0.03 (probabilistic) | +0.43/+0.29 → +0.19/−0.04 |

Reservoir and climatology numbers are unchanged to ±0.01.
