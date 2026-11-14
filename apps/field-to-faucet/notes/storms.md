# storms module: GPM IMERG storm-day sample, POWER check, Earthdata availability

Scripts: `pipeline/p14_imerg.py`, `pipeline/p15_earthdata_check.py`, `pipeline/p16_smap_optional.py`.
Re-run: `python3 pipeline/p14_imerg.py` (free from cache, ~5 s), `python3 pipeline/p15_earthdata_check.py` (~1 min),
`python3 pipeline/p16_smap_optional.py` (exits 0 with a message unless Earthdata credentials exist).

## Why a sample and not a series
- Source: GPM IMERG V06 Final Run, half-hourly, 0.1°, `precipitationCal` (mm/hr), from the Planetary Computer
  `gpm-imerg-hhr` Zarr (`abfs://imerg/gpm-imerg-hhr.zarr`, account `ai4edataeuwest`).
  https://planetarycomputer.microsoft.com/dataset/gpm-imerg-hhr
- The collection ends **2021-05-31**. GES DISC / PPS copies (V07, through 2026) need Earthdata and their hosts are
  blocked by the proxy (see `p15` below).
- Each Zarr chunk is 12 half-hours × the whole globe, blosc-lz4, **51-57 MB**. A local day is 4 chunks (~220 MB),
  whatever the box size. A full daily series for 2016-2021 would be ~430 GB.
- Measured throughput here was **25-30 MB/s** with 6 threads, much faster than the 4 MB/s in the shared notes. So the
  **8 GB** cap, not the 45-min cap, decided the sample size.

## Sample design (`p14_imerg.py`)
- Ranking: NASA POWER `PRECTOTCORR` from `data/processed/power_daily_basin.parquet` (hydro module; area-weighted
  MERRA-2 cells, LST days). Days are ranked by the **max of the two basin means**. If that file is missing, the
  script falls back to the POWER point API at the MERRA-2 cell centres, area-weighted.
- Per year (2016-2020): the **6 wettest Mar-Oct days** plus the **wettest Nov-Feb day**. For 2021 (Jan-May only), the
  season quota is scaled to 3/8 → 2 days, plus 1 winter day. That gives 38 planned days (32 season, 6 winter).
- Priority order: season rank 1 of every year, then rank 2, rank 3, the winter day, then ranks 4-6. The plan is cut
  from the bottom when the budget runs out. The plan is frozen in `data/raw/imerg/sampled_days.json`; delete that
  file to re-sample.
- Local day = 06 UTC d → 06 UTC d+1. This is POWER's LST day for Iowa (UTC-6) and exactly 4 aligned chunks.
- Each chunk is read whole with `adlfs` and decoded with numcodecs Blosc. Only a 29 × 31 px box is kept: lon
  -96.25..-93.45, lat 41.35..44.35. It is cached as `data/raw/imerg/chunk_<i>.npz` (152 files, 3.6 MB total).
- **Download log** (`data/raw/imerg/run_log.json`):
  - Run 1 fetched 136 chunks (7.45 GB, 4.1 min). It dropped 4 rank-6 days on budget: 2017-04-30, 2018-06-19,
    2019-10-05 and 2020-05-17.
  - A rerun then fetched those 4 days (16 chunks, 0.86 GB). At that point the budget was counted per run, which was
    a bug; it is now cumulative across runs.
  - **Total: 152 chunks, 8.31 GB (about 4% over the 8 GB target), 4.7 min. All 38 planned days are present.**

## data/processed/imerg_sample.parquet: 76 rows (38 days × 2 basins), key (basin, date)
| column | units / meaning |
|---|---|
| basin | `raccoon` / `desmoines` |
| date | local day (06 UTC date → 06 UTC next day) |
| imerg_mm | basin-mean daily total, mm. Each 0.1° pixel is weighted by its area inside the basin (EPSG:5070 intersection; pixels on the edge get fractional weight) |
| imerg_max30_mmhr | max half-hour rate over "basin pixels" (≥ 50% of the pixel inside the basin: 97 Raccoon, 180 Des Moines), mm/h |
| imerg_p95_30min | area-weighted 95th percentile, across basin pixels, of each pixel's max half-hour rate, mm/h. A peak intensity that one hot pixel cannot set |
| wet_frac_12p7 | area fraction of the basin with daily total > 12.7 mm (0.5 in, the RUSLE erosive-storm threshold) |
| n_pix | pixels with ≥ 50% inside the basin |
| valid_frac | area-weighted share of pixels with all 48 half-hours valid (1.0 on every row) |
| power_mm | POWER PRECTOTCORR basin mean for the same day, mm (hydro file) |
| sample_class, sample_rank, rationale | `season` (Mar-Oct) or `winter` (Nov-Feb), rank within the year by POWER basin max, plain-text reason |

### Sanity stats
- imerg_mm: mean 24.4, median 22.6, range 2.4-55.1 mm.
- power_mm: mean 24.7, range 5.7-52.1 mm.
- max30: mean 20.2, range 3.8-48.8 mm/h. p95: mean 15.9 mm/h.
- wet_frac_12p7: median 0.86.
- Largest IMERG day: Raccoon 2017-08-21, 55 mm. Highest max30: Des Moines 2018-09-19, 48.8 mm/h, part of the
  September 2018 storm sequence.
- Winter days are much less intense than season days: max30 12.6 vs 21.6 mm/h; totals 16.7 vs 25.9 mm.
- The biggest disagreements are 2017-10-07 (POWER 28-32 mm, IMERG 10-14) and 2019-06-18 Raccoon (POWER 28, IMERG
  4.6). For multi-day events, POWER/MERRA-2 can place the rain on the wrong side of the day boundary.

## data/processed/imerg_vs_power.json
POWER PRECTOTCORR vs IMERG basin totals on the sampled days:

| subset | n | Pearson r | Spearman ρ | bias POWER−IMERG (mm) | volume ratio POWER/IMERG | RMSE (mm) |
|---|---|---|---|---|---|---|
| pooled | 76 | 0.62 | 0.59 | +0.27 | 1.01 | 9.6 |
| Des Moines | 38 | 0.64 | 0.64 | +0.48 | 1.02 | 9.9 |
| Raccoon | 38 | 0.60 | 0.52 | +0.05 | 1.00 | 9.2 |
| season | 64 | 0.57 | 0.54 | +0.53 | 1.02 | 10.2 |
| winter | 12 | 0.71 | 0.59 | −1.15 | 0.93 | 4.8 |

- Heavy-day agreement, using basin mean ≥ 12.7 mm as "heavy": both heavy 63, POWER only 8, IMERG only 2, neither 3.
- POWER's wettest sampled day is also IMERG's wettest in 8 of 12 basin-years.
- The OLS slope of POWER on IMERG is 0.48. POWER compresses the extremes: it is smoother and coarser, at
  ~50 × 50 km.
- Storm-intensity relations (fit on the sampled days, log-log):
  - `max30 = 4.46 · imerg_mm^0.46` (r_log 0.61, residual SD 0.38 in ln units, a factor of about 1.46)
  - `max30 = 2.51 · power_mm^0.63` (r_log 0.56)
  - `p95_30min = 2.79 · imerg_mm^0.54` (r_log 0.71)
  - `wet_frac = 0.39 + 0.0146 · power_mm` (r 0.49)
- **Use in the model:**
  - On POWER-selected wet days, POWER and IMERG volumes agree (ratio 1.01), but POWER compresses extremes (OLS slope
    0.48; e.g. Des Moines 2016-08-11: IMERG 52 mm vs POWER 24 mm). Bias on days that were not selected (e.g. storms
    POWER missed) is untested. POWER ranks storm days moderately well (r = 0.62).
    That supports using it as the continuous rainfall driver for 2016-2026. IMERG is not reachable after 2021-05.
  - The daily total explains only ~37% of the variance of log max-30-min intensity (r_log = 0.61), so storm
    intensity is NOT recoverable from POWER daily totals. The river model therefore uses daily rain amounts and
    antecedent wetness, not intensity; this is a real limitation while IMERG after 2021-05 is unreachable.
  - Day boundary: IMERG days are 06-06 UTC; on 4 back-to-back test pairs, one (2017-10-07) matched POWER better with a
    00-00 UTC day, another (2020-05-17) with the 06 UTC day, so day alignment carries some uncertainty.

## Earthdata availability (`p15_earthdata_check.py` → data/processed/earthdata_check.json)
NASA CMR search worked without login. Granule search used bbox -96.2, 41.4, -93.5, 44.3 and dates 2023-01-01 to
2026-11-14.

| product | version | granules 2023+ | last granule |
|---|---|---|---|
| SPL3SMP_E (SMAP L3 enhanced daily) | 006 | 1,418 | 2026-11-13 |
| SPL4SMGP (SMAP L4 3-hourly, root zone) | 008 | 11,298 | 2026-11-10 |
| GPM_3IMERGDF (IMERG Final daily) | 07 | 1,004 | **2025-09-30** (Final ends there in CMR) |
| GPM_3IMERGDL (IMERG Late daily) | 07 | 1,413 | 2026-11-13 |
| GPM_3IMERGHH (IMERG Final half-hourly) | 07 | 48,192 | 2025-09-30 |
| ECO_L2T_LSTE (ECOSTRESS tiled LST) | 002 | 19,126 | 2026-11-11 |
| TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4 | RL06.3Mv04 | 1 file covering 2002-04 to 2026-09 | |
| GRACEDADM_CLSM0125US_7D (GRACE-DA weekly) | 4.0 | 193 | 2026-08-31 |

- One unauthenticated download was tried per data host. Every attempt failed at the proxy, before Earthdata Login
  could answer: `ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))`.
- The blocked hosts:
  - data.nsidc.earthdatacloud.nasa.gov
  - data.gesdisc.earthdata.nasa.gov
  - data.lpdaac.earthdatacloud.nasa.gov
  - archive.podaac.earthdata.nasa.gov
  - urs.earthdata.nasa.gov
- What unblocks it: those hosts on the allow-list, plus a free Earthdata Login in ~/.netrc or `EARTHDATA_TOKEN`.
  Details are in BLOCKERS.md, "storms / Earthdata".

## p16_smap_optional.py
- With credentials, it does the following:
  - uses `earthaccess` (installed) plus `h5py` (**not installed**: `pip install -q h5py`) to find SPL4SMGP;
  - takes one granule per day (the T133000 file);
  - averages `sm_rootzone` and `sm_surface` over the 9 km cells whose centres fall inside each basin;
  - writes `data/processed/smap_l4_basin_daily.parquet` (basin, date, sm_rootzone, sm_surface, n_cells).
- Without credentials it prints a skip message and exits 0. This was tested.
- The credentialed path is untested, because no credentials were available.

## Caveats
- **Sample ≠ series.** The 38 days were chosen because POWER was wet on them. The correlations are range-restricted
  and conditional on POWER being wet. They do not test days POWER calls dry and IMERG calls wet (false negatives).
- **Areal intensities damp point peaks.** IMERG half-hour rates are 0.1° (~11 × 8 km) areal means. max30 values
  (median 20 mm/h) are far below point-gauge I30, so treat them as relative storminess, not RUSLE I30. The true
  annual maximum intensity may fall on an unsampled day.
- Winter IMERG over snow and frozen ground is less reliable (passive-microwave limits). POWER PRECTOTCORR includes
  snow water equivalent.
- IMERG here is V06; the GES DISC record for 2022+ is V07. Mixing versions would need a cross-check.
- 4 extra days were downloaded beyond the 8 GB target, because of the per-run budget bug described above (now fixed).
