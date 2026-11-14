# Module `model`: river nitrate simulation, validation, bare-soil sensitivity, 14-day outlook

Scripts, run from `apps/field-to-faucet/`. Each is re-runnable end-to-end and reads `data/processed/` fresh every time.
LightGBM runs single-threaded so it is robust when other jobs share the 4 CPUs.

```
python3 model/m01_features.py      # ~2 s    -> model/out/features.parquet
python3 model/m02_river_model.py   # ~4 min  -> river_daily.parquet, metrics.json, models/
python3 model/m03_sensitivity.py   # ~30 s   -> sensitivity.json
python3 model/m04_outlook.py       # ~2 min  -> outlook.json, metrics.json['outlook']
python3 model/m05_figures.py       # ~10 s   -> fig_*.png
```

Library modules:
- `featlib.py`: causal features.
- `qgbm.py`: monotone quantile LightGBM.
- `reservoir.py`: conceptual model.
- `river.py`: the API for the scenario engine.

All numbers below are from the run on 2026-11-14 with data through 2026-11-13 (NWIS) and 2026-11-11 (POWER).

## Bottom line (read this first)
- **Normal years: the drivers-only GBM simulation has real skill.** On the out-of-time test years 2023-2025 it scores NSE 0.58 at Raccoon and 0.60 at Des Moines. Day-of-year climatology scores 0.30 and 0.28, and the conceptual reservoir model 0.38 and 0.55.
- **It badly misses the 2025-2026 high-nitrate regime.** In 2025 Raccoon had 115 observed days above 10 mg/L. The GBM median predicted 7, the reservoir model 0, and climatology 14. Des Moines had 105 observed days; the GBM predicted 10.
  - The cause is a **level shift**. From 2025 Q1 on, observed nitrate is about 1.8-2.1× what the drivers explain. The shift appears in every season and at low, mid and high flow, so it is not a timing error.
  - Out-of-sample annual residuals already swing ×0.65 to ×1.5 in the training years (SD 0.28-0.32 in ln units), and 2025-26 sit at the extreme. Years after droughts run high: 2022 ×1.4-1.5, 2024 ×1.2-1.4, 2025 ×1.8-2.0.
  - This points to a slow state the model does not have: legacy soil and groundwater nitrate after the 2020-2023 drought, plus possible management or N-rate changes. Seven training years cannot teach that.
  - 2025 nitrate data are USGS-approved (`A`), so the shift is **not** a provisional-data artifact. 2026 is about 55% provisional.
- **Where the miss shows up:**
  - The upper end of the calibrated 80% band (p90) exceeds 10 mg/L on 108 of the 115 Raccoon crisis days. So the crisis was "plausible" but not "expected" under the model.
  - 80% band coverage on test is 0.63 at both sites, against the nominal 0.80.
- **Consequences for the app:**
  - Use the simulation for **relative** what-if changes, applied to the observed series ("obs-anchored", as `m03` does). Do not use its absolute level in 2025-26.
  - Use the **outlook**, which is updated with the latest measured nitrate, for near-term levels. It beats persistence at every lead.
- **Bare-soil sensitivity is weakly identified.** It is monotone (less bare soil never raises nitrate) and small: cutting cold-season bare share by 25% lowers simulated nitrate by about 5%, with a 5-95% range of 3-10%. That is about 6 days above 10 mg/L avoided per year (range 3-12). The scenario engine must blend it with trial priors.

## 1. Features (`m01_features.py` → `model/out/features.parquet`, 8,670 rows = 2 sites × 4,335 days, 63 cols)
Rules:
- Every feature at day t uses only data from days ≤ t (trailing windows).
- Weather features are NaN on days without POWER, which covers the 2-day POWER latency at the end. They are never computed from partial windows.
- Basin means come from `power_daily_basin` (`raccoon` for 05484500, `desmoines` for 05482000).

| group | features |
|---|---|
| rain (PRECTOTCORR, mm) | `rain_{1,3,7,14,30,60,90,180,365}` sums; antecedent precipitation indices `api_k85/k95/k98` (API_t = k·API_{t-1} + P_t; e-folding ≈ 6, 20, 50 d) |
| soil wetness | `gwr`, `gwt` (GWETROOT, GWETTOP now), `gwr_7/30/90/365`, `gwt_7/30` means |
| wet rain | `wetrain_{7,30,90}` = Σ P × GWETROOT |
| snow | `melt_{7,30}` = Σ max(0, −ΔSNODP) in cm; `snodp` |
| temperature | `t2m_7/30` means; `gdd5_mar1` = degree-days above 5 °C since the latest Mar 1 (mineralization) |
| cover (MODIS, causal) | `bare` (as-of bare share), `bare_30/90/180` means, `living` = 1 − bare, `living_30` |
| bare × wet | `barewet_{30,90}` = Σ bare × P × GWETROOT (rain landing on bare, wet soil) |
| crops (CDL) | `corn_y`, `corn_prev`. 2015 uses 2016 and 2026 uses 2025 (flag `cdl_extrap`) |
| flow (NWIS, observed driver) | `logq`, `logq_7`, `logq_30`, `dlogq` (1-d), `dlogq_7` |
| season | `doy_sin`, `doy_cos` |
| target | `no3`, `lno3` = ln(no3). Nitrate is **never** a simulation input |

### Cover is causal (how the MODIS gaps were handled)
The modis verifier found that the delivered daily `bare_share` is a centred interpolation, which looks about 16-30 days ahead, and that it drew a straight line across the 2025-07-08..12-30 MODIS gap. Neither is used here.

**As-of value.** Features use the modis module's causal **`bare_share_asof` / `age_days` / `asof_src`**: the latest composite whose 16-day window ended at least 3 days before t. The Jul-Nov 2025 gap is filled from **HLS quantile-mapped to MODIS** (`asof_src='hls'`; 136 Raccoon days, 168 Des Moines days; held-out r = 0.977 per the modis module).
- If those columns are missing, `featlib.cover_asof()` builds the same carry-forward itself from `cover_basin_8day.parquet`. It uses composites with valid_frac ≥ 0.30 and tile_cover_frac ≥ 0.90, available from window end + 3 days.

**Stale values.** When `age_days > 24`, the last observed anomaly against the day-of-year climatology decays toward that climatology with an e-folding of 30 days. This happens in snowy winters and at the trailing edge (the Raccoon h10v04 tile is missing since 2026-10-05). The climatology uses training years 2016-2022 only. Days with no composite at all get the climatology.
- The source of every day is in `cover_src`: `asof_modis`, `asof_hls`, `*_stale_decay` or `clim_no_composite`. For Raccoon the counts are 3,823 / 136 / 195 / 181 (the last are 2015 days, before training).
- The non-causal series is kept only as `bare_centred_diag`, for diagnostics.
- All reported numbers use the HLS-filled as-of series. No run with the earlier, interpolated cover was completed, so no before/after comparison is claimed.

## 2. River simulation models (`m02_river_model.py`)
Splits: **train** 2016-2022, **test** 2023-2025 (out-of-time), **live** 2026-01-01..2026-11-11 (out-of-sample; POWER ends 11-11).

### (a) Monotone quantile GBM
- **Target and quantiles.** ln(no3) at quantiles 0.1, 0.5 and 0.9.
- **Monotone (+) constraints** on all bare-share features (`bare*`), bare × wet (`barewet_*`) and soil wetness (`gwr*`, `gwt*`).
- **Custom objective.** LightGBM's built-in `quantile` objective refuses monotone constraints, so quantiles use a custom pinball-loss objective (unit Hessian, `qgbm.py`).
  - The 0.1 and 0.9 models are boosted as offsets from the median model. Starting from a constant left the tails stuck near the unconditional quantile, because the step per tree is at most lr·α.
- **Hyperparameters** come from leave-one-year-out (LOYO) CV inside 2016-2022 only. The score is the mean ln-RMSE of the median model.
  - Grid: num_leaves {7, 15} × min_child_samples {50, 150} × trees {150, 400, 800} at lr 0.03, × optional feature groups "long memory" (`rain_365`, `gwr_365`) and "CDL" (`corn_y`, `corn_prev`).
  - Fixed settings: feature_fraction 0.7, bagging 0.8, λ₂ = 1, max_bin 127.

  | site | leaves | min_child | trees | long memory | CDL | LOYO ln-RMSE | LOYO NSE (mg/L, pooled) |
  |---|---|---|---|---|---|---|---|
  | Raccoon 05484500 | 15 | 150 | 150 | no | yes | 0.517 | 0.73 |
  | Des Moines 05482000 | 7 | 50 | 400 | yes | yes | 0.490 | 0.63 |

  - CV picked the year-constant CDL corn shares at both sites. They can act partly as a year identifier, so treat their contribution with suspicion.
  - Des Moines picked the 365-day memory features, which is consistent with the Saylorville lag.
- **80% band: conformalized (CQR).** LOYO out-of-fold quantiles give conformity scores, and the band is widened in log space by q̂ = +0.41 (Raccoon) and +0.48 (Des Moines), roughly ×/÷1.5-1.6.
  - Raw LOYO coverage was only 0.26 and 0.11, because the flexible median fits training years almost perfectly.
  - The band is therefore dominated by honest out-of-year error.

### (b) Two-reservoir conceptual model (`reservoir.py`)
Daily, in arbitrary N units (the mineralization rate is fixed at 1 to fix the scale):

| process | equation |
|---|---|
| snow | rain falls as snow when T ≤ 0; melt is 3 mm/°C/day |
| drainage | W ← W + (rain + melt)·GWETROOT^p; D = W/τ_d |
| soil N pool | S ← S + M + Fert − U − L − d·S |
| mineralization | M = 1.07^(T−20) for T > 0, else 0 |
| fertilizer | Fert = fert·corn·[(1−ff)·spring(Apr 10-May 31) + ff·fall(Nov)] |
| uptake | U = u·living·GWETROOT·f(T)·S (living-cover uptake, water- and temperature-limited) |
| leaching | L = k·S·D |
| river mixing store | R ← R + L − R/τ_r |
| concentration | C = c0 + a·(R/τ_r)/(Q/Q_med)^β |

- Fitting: 11 parameters, fitted on ln C over 2016-2022 with `scipy.optimize.least_squares` (soft-L1 loss, log-space parameters, 4 starts that agree), with 3 years of spin-up.
- Uptake was made temperature-limited *before* looking at test scores. Without it, the summer-crop uptake rate was applied to winter cover, which is physically wrong.
- The 80% band comes from training residual quantiles.
- Fitted parameters are in `models/config_<site>.json`. Several sit at bounds: ff = 0.7 (fall N), p = 4.8-6 (drainage only when the soil is wet), β = 0 (concentration not diluted by flow). That signals structural limits; read it as a transparent cross-check, not the main model.

### (c) Baselines
- **Climatology:** day-of-year (±15 d) quantiles of ln no3 in 2016-2022.
- **Persistence 7 d and 14 d:** the observation 7 or 14 days earlier.
  - These use measured nitrate, so they are *forecasts*, not simulations. They are listed for the contract and naturally score high (NSE 0.65-0.90).
  - Compare them with the outlook (section 4), not with the simulation.

### Validation table (concentration in mg/L; days with an observation; 80% coverage; exceedance at 10 mg/L by the p50)
"Train" rows for the GBM are **LOYO CV**; in-sample fit is NSE 0.97-0.99 and meaningless.

| site | split | model | NSE | KGE | RMSE | bias | cov80 | obs / pred days > 10 | hit rate | FAR | CSI |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Raccoon | train (LOYO) | GBM | 0.73 | 0.78 | 1.87 | −0.26 | – | 307 / 159 | 0.30 | 0.43 | 0.24 |
| Raccoon | test 23-25 | **GBM** | **0.58** | 0.57 | 2.71 | −1.53 | 0.63 | 189 / 63 | 0.33 | 0.02 | 0.33 |
| Raccoon | test 23-25 | reservoir | 0.38 | 0.49 | 3.33 | −1.47 | 0.55 | 189 / 41 | 0.21 | 0.02 | 0.21 |
| Raccoon | test 23-25 | climatology | 0.30 | 0.41 | 3.52 | −0.12 | 0.65 | 189 / 42 | 0.15 | 0.33 | 0.14 |
| Raccoon | test 23-25 | persistence 7 d | 0.76 | 0.88 | 2.02 | −0.05 | 0.67 | 179 / 181 | 0.76 | 0.25 | 0.61 |
| Raccoon | test 23-25 | persistence 14 d | 0.65 | 0.83 | 2.42 | −0.04 | 0.71 | 177 / 179 | 0.70 | 0.31 | 0.53 |
| Raccoon | live 2026 | GBM | −0.11 | 0.43 | 4.37 | −3.55 | 0.60 | 174 / 8 | 0.05 | 0.00 | 0.05 |
| Raccoon | live 2026 | reservoir | −1.04 | 0.24 | 5.91 | −5.03 | 0.30 | 176 / 8 | 0.05 | 0.00 | 0.05 |
| Raccoon | live 2026 | climatology | −0.49 | 0.38 | 5.05 | −4.07 | 0.51 | 176 / 14 | 0.07 | 0.07 | 0.07 |
| Des Moines | train (LOYO) | GBM | 0.63 | 0.79 | 2.13 | 0.00 | – | 183 / 164 | 0.39 | 0.57 | 0.26 |
| Des Moines | test 23-25 | **GBM** | **0.60** | 0.56 | 2.84 | −1.33 | 0.63 | 166 / 31 | 0.19 | 0.00 | 0.19 |
| Des Moines | test 23-25 | reservoir | 0.55 | 0.69 | 2.99 | −0.79 | 0.73 | 166 / 60 | 0.33 | 0.10 | 0.31 |
| Des Moines | test 23-25 | climatology | 0.28 | 0.32 | 3.81 | +0.10 | 0.76 | 166 / 0 | 0 | – | 0 |
| Des Moines | test 23-25 | persistence 7 d | 0.90 | 0.95 | 1.43 | −0.04 | 0.78 | 166 / 167 | 0.84 | 0.17 | 0.72 |
| Des Moines | live 2026 | GBM | −1.95 | 0.33 | 5.14 | −4.78 | 0.21 | 156 / 0 | 0 | – | 0 |
| Des Moines | live 2026 | reservoir | −3.23 | 0.21 | 6.13 | −5.66 | 0.27 | 158 / 0 | 0 | – | 0 |
| Des Moines | live 2026 | climatology | −1.34 | 0.44 | 4.56 | −4.10 | 0.48 | 158 / 0 | 0 | – | 0 |

GBM test NSE by year:

| site | 2023 | 2024 | 2025 |
|---|---|---|---|
| Raccoon GBM | 0.59 | 0.83 | −1.05 |
| Raccoon climatology | −0.83 | 0.68 | −1.49 |
| Des Moines GBM | 0.54 | 0.76 | −0.17 |

The model tracks timing well (the 2023 drought, the 2024 June flush) but not the 2025 level.

**Where the model is worse than climatology:**
- In 2026 live, **climatology beats the GBM at Des Moines** (NSE −1.34 vs −1.95). Both are far below zero.
- At Des Moines the reservoir model has higher KGE than the GBM on test (0.69 vs 0.56), because the GBM's variability ratio is low: it is too smooth and under-predicts peaks.
- Investigation: see `metrics.json → sites.<site>.residual_diagnostics`. The out-of-sample residual is a near-constant multiplicative level offset per year (2025 ×1.79 Raccoon, ×1.96 Des Moines; 2026 ×1.52 / ×2.08), in every flow tercile. Climatology "wins" in 2026 only because it is flat and the river sat at ~10-12 mg/L almost all year.

**2025 crisis block** (on days with observations; `metrics.json → crisis_2025`):

| site | observed days > 10 | GBM p50 | GBM p90 > 10 | reservoir | climatology | peak observed | peak GBM |
|---|---|---|---|---|---|---|---|
| Raccoon | 115 (first 03-26, still > 10 on 12-31) | 7 (06-28..07-04) | 108 | 0 | 14 | 18.4 on 06-07 | 10.9 on 07-02 |
| Des Moines | 105 (04-09..08-06) | 10 (06-30..07-10) | 82 | 0 | 0 | 17.0 on 06-12 | 12.0 on 07-04 |

The 2026 block (`live_2026`): Raccoon 176 observed days > 10 vs GBM 8 (p90 > 10 on 178 days); Des Moines 158 vs 0 (p90 81).

## 3. Bare-soil sensitivity (`m03_sensitivity.py` → `sensitivity.json`; API `river.py`)
**Method.**
- The causal daily bare share is cut by 10/25/50% of its value on Oct 15-May 31 every year, and living share rises by the same amount.
- Every cover-derived feature is recomputed (`river.perturb_cover`), and the models re-predict.
- Effects are reported as % change of the p50 simulation, and as days above 10 mg/L avoided per year when the model's ratio cf/base is applied to the **observed** series ("obs-anchored", which sidesteps the level bias).
- Uncertainty: 30 refits of the median GBM on bootstrap-resampled training *years*, plus the p10/p90 models, plus the reservoir model as a structurally different estimate.

| site | bare cut (Oct 15-May 31) | GBM Δ nitrate in window (boot 5-95%) | GBM Δ Apr-Jul | days > 10 avoided per year, 2016-25 mean (boot) | 2025 days avoided (boot) | elasticity d ln C / d bare | reservoir Δ window / days per year |
|---|---|---|---|---|---|---|---|
| Raccoon (obs mean 49.6 d/yr) | −10% | −3.0% (−4.9..−1.8) | −1.7% | 2.7 (0.7-5.2) | 3 (1-7) | 0.36 (0.18-0.58) | −10.5% / 23 |
| | −25% | −5.2% (−7.1..−3.3) | −3.7% | 6.4 (2.9-11.3) | 7 (3-25) | 0.25 | −22.6% / 43 |
| | −50% | −8.3% (−11.7..−5.0) | −8.4% | 14.7 (6.3-24.4) | 14 (7-46) | 0.19 | −36.7% / 47 |
| Des Moines (obs mean 34.9 d/yr) | −10% | −3.5% (−5.7..−2.7) | −2.1% | 2.9 (1.4-5.6) | 9 (4-17) | 0.39 | −5.3% / 8 |
| | −25% | −5.7% (−9.9..−4.3) | −4.7% | 5.8 (3.5-12.2) | 18 (8-40) | 0.24 | −12.3% / 21 |
| | −50% | −9.1% (−15.8..−7.4) | −10.5% | 11.1 (7.5-23.7) | 33 (13-74) | 0.19 | −21.8% / 33 |

The p10 and p90 models shift by similar amounts, for example −4 to −6% for a 25% cut.

**Identification: read before using.** The effect is weakly identified, for these reasons:
- **Variation is mostly seasonal.** 98% of training-period variance in bare share is the day-of-year cycle. The Oct-May mean bare share varies between seasons with an SD of only 0.025 (Raccoon) and 0.019 (Des Moines); seasonal means are 0.86-0.94. Its year-to-year changes are weather (green-up and harvest timing), not cover-crop adoption.
- **The perturbation leaves the training range.** A 10% cut is already 3.6-4.8 interannual SDs. On 51-63% of window days, the perturbed bare share is below anything seen in training for that week; for a 50% cut it is 88-90%. Trees extrapolate flat there, so the GBM response **saturates**: the elasticity falls from 0.36-0.39 at 10% to 0.19 at 50%.
- **Bare-share features add little skill.** Dropping them raises LOYO ln-RMSE by only 0.015 (Raccoon) and 0.014 (Des Moines), about 3%.
- **The constraint fixes direction, not size.** The monotone constraint guarantees the sign: less bare soil never raises nitrate. The size is shaped by the seasonal confound.
- **The reservoir response is an implausible upper bound.** Its living-cover uptake rate is learned mostly from summer crops, where living cover is confounded with crop N uptake. Its −10 to −37% responses are much larger than field trials support. For context, cereal rye cuts tile nitrate loss by ~30% *on the fields that adopt it*.
- **So:** the GBM's −3 to −9% (for 10-50% less cold-season bare soil) is the data-driven estimate. The scenario engine should blend it with trial priors and show ranges.

**API (`model/river.py`):**
- `load_models()` → dict per site.
- `predict(features_df, site, models)` → DataFrame of p10, p50, p90 in mg/L, CQR band, aligned to the input index.
- `perturb_cover(features_df, frac, months='oct15-may31' | [month numbers])` → a copy with bare scaled by (1 − frac) in the window and every cover feature recomputed. Pass full continuous daily series per site (from 2015-10-01) so the 180-day windows are right.
- `predict_reservoir(features_df, site, models)` → reservoir p50.

## 4. 14-day outlook (`m04_outlook.py` → `outlook.json`, contract schema plus `sites{}` for both gauges)
**Model.** LightGBM quantile models (τ = 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95; 300 trees, 7 leaves) predict ln(no3[t+h]/no3[t]) for h = 1..14.
- **Inputs:** the last measured nitrate, its 3- and 7-day change, flow and flow trend through t, and season. Weather and cover drivers are taken *as of t−2*, matching the real POWER latency (the lag is computed at run time): rain 3-90 d, API, wetness, wet rain, melt, snow depth, temperature, degree-days, bare share and bare × wet.
- **No weather forecast is used** (none is available here). Future rain is implicitly "typical for the season".
- **Interval calibration.** Raw quantile bands under-covered on 2023-2025 (Raccoon 0.61 at h7, 0.57 at h14). The issued 80% band is therefore the GBM band widened by a lead-specific factor k, calibrated to 80% coverage on 2023-2025: k = 1.15→1.85 (Raccoon) and 1.0→1.4 (Des Moines).
- **Calibration check:** on live 2026, with models trained 2016-2025, the calibrated bands covered 0.82 (h7) and 0.73 (h14) at Raccoon, and 0.80 and 0.85 at Des Moines.
- `prob_over10` comes from interpolating the quantile function, clipped to [0.01, 0.99].
- Driver percentiles compare against the same ±7-day calendar window in 2016-2025.

**Skill** (`metrics.json → outlook`; RMSE in mg/L; "skill" = 1 − MSE/MSE_persistence):

| site | period | lead | GBM RMSE | persistence | climatology of change | MSE skill vs persistence | Brier skill (P > 10) | cov80 |
|---|---|---|---|---|---|---|---|---|
| Raccoon | test 23-25 | 7 d | 1.84 | 2.04 | 2.01 | +19% | +33% | 0.61 raw |
| Raccoon | test 23-25 | 14 d | 2.15 | 2.46 | 2.37 | +24% | +29% | 0.57 raw |
| Raccoon | live 2026 | 7 d | 1.98 | 2.48 | 2.33 | +36% | +38% | 0.82 calibrated |
| Raccoon | live 2026 | 14 d | 2.65 | 3.50 | 3.00 | +43% | +32% | 0.73 calibrated |
| Des Moines | test 23-25 | 7 d | 1.12 | 1.44 | 1.46 | +39% | +43% | 0.74 raw |
| Des Moines | test 23-25 | 14 d | 1.88 | 2.08 | 2.06 | +18% | +29% | 0.70 raw |
| Des Moines | live 2026 | 7 d | 1.35 | 1.68 | 1.61 | +35% | +46% | 0.80 calibrated |
| Des Moines | live 2026 | 14 d | 1.94 | 2.24 | 2.05 | +25% | +31% | 0.85 calibrated |

- The exceedance CSI is about the same as persistence (Raccoon h14: 0.50 vs 0.52). The gain is mostly in magnitude and probabilities, not in yes/no calls.
- Issued 2026-11-14 from the 2026-11-13 observation:
  - Raccoon: 11.6 mg/L → median 11.2 by Nov 27 (80% range 9.8-12.3), about 12 of 14 days above 10.
  - Des Moines: 11.1 → 9.9 (8.8-12.2), about 11 of 14 days.

## 5. Outputs
| file | content |
|---|---|
| `model/out/features.parquet` | daily drivers per site (see section 1), incl. `cover_src`, `cover_age_days`, `bare_asof_raw`, `bare_centred_diag` (diagnostic only) |
| `model/out/river_daily.parquet` | 7,940 rows (2 sites, 2016-01-01..2026-11-13). Columns: site, date, obs, q_cfs, p10, p50, p90 (GBM, CQR band), split, reservoir_p50/p10/p90, clim_p50/p10/p90, pers7, pers14, gbm_loyo_p50 (out-of-fold, train years), cover_src, no3_qual. NaN predictions on 11-12/11-13 (no POWER yet) |
| `model/out/metrics.json` | per site: hyperparameters, CV top 5, splits{train,test,live}{gbm, reservoir, climatology, persistence_7d, persistence_14d, gbm_loyo_cv(train)}: NSE, KGE, RMSE, MAE, bias, pbias, r, NSE_log, coverage80, exceed10{obs_days, pred_days, hits, misses, false_alarms, hit_rate, false_alarm_ratio, csi}; test_by_year; crisis_2025 and live_2026 per model; by_year_days_over10; residual_diagnostics. Plus `outlook` (per site, every lead) |
| `model/out/sensitivity.json` | perturbation spec, identification caveat, per site: gbm{frac: central + bootstrap}, gbm_p10, gbm_p90, reservoir, diagnostics |
| `model/out/outlook.json` | web contract fields (Raccoon at top level) plus `sites{05484500, 05482000}` with p05/p95, expected_days_over10, interval factors, skill |
| `model/out/models/` | `gbm_<site>_q{10,50,90}.txt` (+ `.meta.json` with init score and base model), `config_<site>.json` (features, monotone vector, hyperparameters, CQR q̂, reservoir parameters) |
| `model/out/fig_river_2016_2026.png`, `fig_2025_zoom.png`, `fig_scatter.png`, `fig_outlook.png`, `fig_sensitivity.png` | documentation figures |

## 6. Limitations (honest list)
1. **Identification.** Historical cover variation is seasonal and weather-driven, so the learned bare-share effect is weak and saturating (section 3). Blend it with trial priors.
2. **Missing slow state: legacy N and groundwater lag.** Year-level offsets (SD ~0.3 ln) are the dominant error, and 2025-26 are about 2× the drivers. No input describes soil-N carry-over after drought, groundwater nitrate residence (years to decades) or changing N rates. Seven training years cannot learn this. The longest memory is 365 days, and LOYO did not reward it at Raccoon.
3. **Saylorville Reservoir.** The Des Moines gauge sits below a reservoir that stores, mixes and partly denitrifies water. Longer-memory features help a little, but there is no reservoir routing. Des Moines live-period skill is the worst of all.
4. **MODIS cover.** It is 250 m and mixes field edges and waterways. NDVI 0.30 is a relative index, not "% of fields bare".
   - Jul-Nov 2025 is an HLS fill.
   - The Raccoon as-of value is 27-30 days stale at issue time (tile missing on PC) and decays toward climatology.
   - The winter living share is not a cover-crop map.
5. **POWER vs IMERG.** Rain is MERRA-2/GEOS-IT at ~50 km. On 76 sampled storm days, POWER had no volume bias against IMERG (ratio 1.01) and r = 0.62, but it smooths peaks: the OLS slope is 0.48. There is no continuous IMERG after 2021-05 and no storm-intensity input. The GEOS-IT period in 2026 may carry a small level shift.
6. **NWIS.** Data from about mid-2025 on are provisional (2026 is about 55% `P`). Gaps are not filled, and exceedance days are counted on observed days only.
7. **Flow is an input.** The simulation uses observed discharge, so it is a "given the observed hydrology" model. For scenarios, cover changes are assumed not to change flow.
8. **CDL.** Corn shares are year-constant features (CV picked them), and 2026 reuses 2025.
9. **Outlook.** It has no weather forecast, so storms are not anticipated. Calibrated bands rest on 3 calibration years. Yes/no exceedance calls are no better than persistence.
