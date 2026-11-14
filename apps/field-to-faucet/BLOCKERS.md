# Blockers and workarounds

Each module appends a section: what failed (exact error), what we used instead, and what would unblock it.

## Network policy (orchestrator, 2026-11-14)
- The cloud container's default network policy blocked every data host (`403` on CONNECT for waterservices.usgs.gov,
  planetarycomputer.microsoft.com, power.larc.nasa.gov, hydro.nationalmap.gov, ...). Fixed by creating an environment
  with an explicit allow-list (see CONTRACTS.md, "Network"). Hosts not on that list are still blocked.
- `nassgeodata.gmu.edu` (CropScape) is allowed but does not respond (curl exit 000 / empty reply after 0.4 s and on
  120 s retry). Workaround: official national CDL zips from www.nass.usda.gov for 2022-2025.

## hydro
- **NHD large-scale flowlines time out.** `GET https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query`
  (layer 6 "Flowline - Large Scale"), even with only `where=gnis_name='Raccoon River'&returnCountOnly=true`, returned
  `504 Gateway Timeout ERROR` (CloudFront, "The request could not be satisfied") after 60 s, twice on 2026-11-14.
  Workaround: layer 4 "Flowline - Small Scale" (NHDPlus V2, 1:100k) answers in < 2 s and has `StreamOrde`, which the
  map needs anyway. `web/data/rivers.geojson` is built from it.
- **POWER `PRECSNOLAND` is missing (-999) for every cell from 2026-10-01**, and `ALLSKY_SFC_SW_DWN` on 2026-09-07,
  2026-11-10 and 2026-11-11. That is the near-real-time GEOS-IT/FLASHFlux period. These are left as NaN, with nothing filled in.
  The core drivers (PRECTOTCORR, T2M*, GWET*, SNODP) are complete through 2026-11-11.
- **NWIS IV fill was not needed.** dv has nitrate and flow through 2026-11-13 at both sites. The few missing recent dv
  days (05482000 nitrate, 2026-07-27) have fewer than 80 IV readings as well. The IV code path runs anyway; it filled 0 days.

## storms / Earthdata (storms module, 2026-11-14)
- **GPM IMERG 2022-2026 and full daily IMERG series: blocked.** The only credential-free IMERG copy is Planetary
  Computer `gpm-imerg-hhr` (V06), which ends 2021-05-31; each Zarr chunk is 12 half-hours of the whole globe
  (~51-57 MB), i.e. ~220 MB per local day. Used instead: a POWER-ranked storm-day sample 2016-01..2021-05
  (38 days, 8.3 GB, `pipeline/p14_imerg.py` -> `data/processed/imerg_sample.parquet`, `imerg_vs_power.json`), which
  shows that on POWER-selected wet days POWER and IMERG volumes agree (ratio 1.01, r = 0.62) but POWER compresses
  extremes (slope 0.48) and storm intensity cannot be recovered from POWER daily totals.
  POWER PRECTOTCORR is therefore the continuous rain driver for 2016-2026.
- **CMR search works (no login)** and confirms granules over the basins for 2023-2026 (`p15_earthdata_check.py` ->
  `data/processed/earthdata_check.json`): SPL3SMP_E v006 (1,418 daily, through 2026-11-13), SPL4SMGP v008 (11,298
  3-hourly, through 2026-11-10), GPM_3IMERGDL v07 (1,413 daily, through 2026-11-13), GPM_3IMERGDF v07 (1,004 daily,
  **ends 2025-09-30** in CMR), GPM_3IMERGHH v07 (ends 2025-09-30), ECO_L2T_LSTE v002 (19,126 tiles), GRACE/GRACE-FO
  JPL mascon RL06.3 v4 (one file, `GRCTellus.JPL.200204_202609...nc`, through 2026-09), GRACEDADM_CLSM0125US_7D
  (weekly, through 2026-08-31).
- **Downloads fail before authentication.** Every data host is refused by the container proxy, so the expected
  401 / redirect to Earthdata Login is never reached. Exact error (same for each host):
  `ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))` for
  data.nsidc.earthdatacloud.nasa.gov (SMAP), data.gesdisc.earthdata.nasa.gov (IMERG, GRACE-DA),
  data.lpdaac.earthdatacloud.nasa.gov (ECOSTRESS), archive.podaac.earthdata.nasa.gov (GRACE-FO), and
  urs.earthdata.nasa.gov (Earthdata Login itself). There are no credentials either (no `EARTHDATA_TOKEN`, no ~/.netrc).
- **What unblocks it:** (1) add those 5 hosts to the environment's network allow-list; (2) a free NASA Earthdata
  Login (https://urs.earthdata.nasa.gov/users/new) with the GES DISC and NSIDC apps approved, saved as ~/.netrc
  (`machine urs.earthdata.nasa.gov login <user> password <pass>`) or `EARTHDATA_TOKEN`. Code paths that would then
  run: `pipeline/p16_smap_optional.py` (SMAP L4 root-zone soil moisture per basin via earthaccess ->
  `data/processed/smap_l4_basin_daily.parquet`; exits cleanly today), and IMERG Late/Final daily for 2022-2026 could
  replace POWER rain via the same basin-weighting code as `p14_imerg.py` (not written).

## modis (2026-11-14)
- **Planetary Computer `modis-13Q1-061` has no MOD13Q1 or MYD13Q1 items after Terra A2025177 (window Jun 26-Jul 11,
  2025) until Terra A2025321 (Nov 17)**: the first missing composite is Aqua A2025185 (start 2025-07-04), the last Aqua
  A2025313 (start 2025-11-09), 17 windows, anywhere on the globe (STAC search over Iowa returns 0 items; a global search
  for Aug-Oct 2025 returns 0). `modis-09A1-061`, `modis-13A1-061`, `modis-43A4-061`, `modis-15A2H-061` and
  `modis-11A2-061` have the same gap; `modis-09Q1-061` has a single h11v04 item. CMR shows the granules exist at LP DAAC
  (e.g. `MOD13Q1.A2025193.h10v04.061.2025212122128` ... `MOD13Q1.A2025305.h11v04.061.2025322130317`), but downloading
  needs an Earthdata login and the LP DAAC data host is not on the proxy allow-list.
- **Workaround in place: NASA HLS v2 gap-fill** (`pipeline/p09b_hls_gapfill.py`, PC `hls2-l30` + `hls2-s30`, 7 MGRS
  tiles, 1,526 scenes, 0 read failures, ~7 min). HLS composites built on the MODIS windows and mask, quantile-mapped to
  MODIS NDVI on 2023/2024/2025 overlap windows (living share bias −0.001, r 0.989, RMSE 0.062; leave-one-year-out RMSE
  0.086, fall-only 0.132). They fill the 17 windows in `cover_basin_8day` / `cover_basin_daily` with
  `gapfill_src = 'hls'` (HUC-12 level: `cover_hls_huc12_8day.parquet`). Fall 2025 bare = 0.705 Raccoon / 0.704 Des
  Moines. These values carry the HLS-vs-MODIS calibration error (notes/modis.md). Unblock for true MODIS: an Earthdata
  token + allow `data.lpdaac.earthdatacloud.nasa.gov`, or wait for PC to backfill (p09 then fetches the new items and
  the MODIS composites automatically take precedence over HLS in those windows).
- The h10v04 tile (west ~57% of the Raccoon mask) is missing on PC for composites MYD13Q1.A2025361 (date 2026-01-04)
  and the two latest ones, MYD13Q1.A2026281 / MOD13Q1.A2026289 (dates 2026-10-16/24). Those rows are kept in
  `cover_basin_8day` with `tile_cover_frac` 0.43 (raccoon) / 0.98 (desmoines) and excluded from the daily series when
  `tile_cover_frac < 0.9`, so the Raccoon interpolated series ends 2026-10-05 (Des Moines 2026-10-20) and the Raccoon
  as-of value on 2026-11-14 is 30 days old (not yet stale). In `cover_huc12_8day` the affected HUC-12 rows have
  `tile_cover_frac < 0.5` and NaN shares.

## fields (2026-11-14)
- Not a failure; partial coverage. Planetary Computer HLS v2 holdings for tile T15TUG are incomplete. In 2023, NASA CMR
  lists 85 HLSS30 and 79 HLSL30 granules with cloud cover <= 80, but PC returns 42 S30 and 53 L30 that intersect the
  focus bbox. PC L30 is also thin in 2020-21 (22-25 granules per year). We used everything PC has: 591 granules, of
  which 522 had clear pixels. That gives a median of 40 clear observations per field-year for 2021-26.
- Unblock: download the missing granules from LP DAAC with an Earthdata token (optional path, not implemented).
