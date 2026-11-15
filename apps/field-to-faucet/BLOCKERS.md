# Field to Faucet: blockers and workarounds

Every data source we could not reach, the exact error, what we used instead, and what would unblock it. Consolidated on
2026-11-15 from the module sections (hydro, cdl, modis, fields, storms, fields_model, facts, frontend). Module notes in
`notes/*.md` hold the full detail. No number in the app was invented to fill a gap: gaps are left empty, filled from a
documented real alternative, or the claim is dropped.

## Summary

| # | blocked source | exact error | workaround used | what unblocks it |
|---|---|---|---|---|
| 1 | Default container network (all data hosts) | `403` on CONNECT | Environment with an explicit host allow-list | Done |
| 2 | NASA Earthdata downloads: SMAP, IMERG V07 (incl. after 2021-05), LP DAAC (MODIS fill, ECOSTRESS, missing HLS), GRACE/GRACE-FO | `ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))`; no credentials | POWER GWETROOT for soil wetness; POWER PRECTOTCORR for rain, IMERG V06 sample to check it; HLS fill for MODIS; ECOSTRESS and GRACE not used | 5 Earthdata hosts on the allow-list + a free Earthdata Login (`~/.netrc` or `EARTHDATA_TOKEN`) |
| 3 | IMERG on Planetary Computer after 2021-05-31 | collection ends 2021-05-31; ~220 MB of global data per local day | 38-day storm sample 2016-2021 (8.3 GB) | #2 |
| 4 | MODIS 13Q1 on Planetary Computer, Jul-Nov 2025 | 0 STAC items for 17 composites (Aqua A2025185 to Aqua A2025313) | Quantile-mapped HLS composites (`p09b_hls_gapfill.py`) | Earthdata + LP DAAC host, or PC backfill (code picks it up) |
| 5 | MODIS tile h10v04 on PC, 3 composites | tile missing (2026-01-04, 2026-10-16, 2026-10-24) | Composites kept but excluded from the daily series; as-of value carried forward | PC backfill |
| 6 | HLS on PC before 2020 and incomplete for tile 15TUG | `hls2-l30`/`hls2-s30` start 2020-01-01; 2023: PC 42 S30 + 53 L30 vs CMR 85 + 79 | All 591 PC granules used (median 36 clear views per field-year, 2021-26); 2016-19 field values reuse each field's 2020-25 pattern | Earthdata + LP DAAC host (download path not implemented) |
| 7 | CropScape (nassgeodata.gmu.edu) | no response (curl exit 000 / empty reply after 0.4 s and on 120 s retry) | NASS national CDL zips 2022-2025 + PC `usda-cdl` 2011-2021 | not needed |
| 8 | NHD large-scale flowlines (MapServer layer 6) | `504 Gateway Timeout ERROR` (CloudFront) after 60 s, twice | NHDPlus V2 small-scale flowlines (layer 4) | Retry later; not needed |
| 9 | NASS Quick Stats API | none: no key needed | CDL from bulk downloads; crop shares computed from CDL | – |
| 10 | Web hosts for facts | blocked by proxy, or allowed but connection dropped (HTTP/2 INTERNAL_ERROR / empty reply) | Facts kept as `secondary`, or dropped if `unverified` | Allow-list the hosts and re-verify |
| 11 | NASA POWER recent fields | `PRECSNOLAND` = −999 from 2026-10-01; `ALLSKY_SFC_SW_DWN` missing on 3 days | Left NaN; snow inferred from T2M ≤ 0 °C where needed | POWER backfill |
| 12 | SMAP code path dependency | `h5py` not installed | `p16_smap_optional.py` exits cleanly without credentials | `pip install -q h5py` + #2 |

---

## 1. Container network policy

- The cloud container's default policy blocked every data host (`403` on CONNECT for waterservices.usgs.gov,
  planetarycomputer.microsoft.com, power.larc.nasa.gov, hydro.nationalmap.gov, ...).
- **Fixed** by an environment with an explicit allow-list (`CONTRACTS.md`, "Network"): waterservices.usgs.gov,
  api.waterdata.usgs.gov, planetarycomputer.microsoft.com and its blob stores, power.larc.nasa.gov,
  hydro.nationalmap.gov, sdmdataaccess.sc.egov.usda.gov, www.nass.usda.gov, cmr.earthdata.nasa.gov (search only),
  www2.census.gov, prd-tnm.s3.amazonaws.com. Hosts not on the list are still blocked.

## 2. NASA Earthdata downloads (SMAP, IMERG V07, LP DAAC, ECOSTRESS, GRACE)

**What works.** NASA CMR search, without login (`pipeline/p15_earthdata_check.py` → `data/processed/earthdata_check.json`;
bbox −96.2, 41.4, −93.5, 44.3; 2023-01-01 to 2026-11-14):

| product | version | granules 2023+ | last granule |
|---|---|---|---|
| SPL3SMP_E (SMAP L3 enhanced, daily) | 006 | 1,418 | 2026-11-13 |
| SPL4SMGP (SMAP L4 3-hourly, root zone) | 008 | 11,298 | 2026-11-10 |
| GPM_3IMERGDF (IMERG Final, daily) | 07 | 1,004 | **2025-09-30** (Final ends there in CMR) |
| GPM_3IMERGDL (IMERG Late, daily) | 07 | 1,413 | 2026-11-13 |
| GPM_3IMERGHH (IMERG Final, half-hourly) | 07 | 48,192 | 2025-09-30 |
| ECO_L2T_LSTE (ECOSTRESS tiled LST) | 002 | 19,126 | 2026-11-11 |
| TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4 (GRACE/GRACE-FO JPL mascons) | RL06.3Mv04 | 1 file, 2002-04 to 2026-09 | |
| GRACEDADM_CLSM0125US_7D (GRACE data assimilation, weekly) | 4.0 | 193 | 2026-08-31 |

**What fails.** One unauthenticated download per data host. Every attempt failed at the container proxy, before
Earthdata Login could answer:

```
ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))
```

| host | holds |
|---|---|
| data.nsidc.earthdatacloud.nasa.gov | SMAP |
| data.gesdisc.earthdata.nasa.gov | IMERG V07, GRACE-DA |
| data.lpdaac.earthdatacloud.nasa.gov | ECOSTRESS, MODIS 13Q1 (2025 fill), HLS (missing granules) |
| archive.podaac.earthdata.nasa.gov | GRACE-FO |
| urs.earthdata.nasa.gov | Earthdata Login itself |

There are no credentials either (no `EARTHDATA_TOKEN`, no `~/.netrc`).

**Workarounds used.**
- **SMAP soil moisture → NASA POWER GWETROOT** (root-zone wetness, MERRA-2) as the wetness driver everywhere (drainage
  gate, river model, leak calendar, outlook).
- **IMERG → NASA POWER PRECTOTCORR** as the continuous rain driver 2016-2026, checked against an IMERG V06 sample (§3).
- **ECOSTRESS and GRACE:** not used. The app does not claim evapotranspiration or groundwater storage.
- **MODIS 2025 gap:** §4. **Missing HLS granules:** §6.

**What unblocks it.**
1. Add the 5 hosts above to the environment's network allow-list.
2. A free NASA Earthdata Login (https://urs.earthdata.nasa.gov/users/new) with the GES DISC and NSIDC applications
   approved, saved as `~/.netrc` (`machine urs.earthdata.nasa.gov login <user> password <pass>`) or as
   `EARTHDATA_TOKEN`. Never commit it.

Code paths that would then run:
- `pipeline/p16_smap_optional.py`: SMAP L4 root-zone and surface soil moisture per basin via `earthaccess`
  (one granule per day, 9 km cells inside each basin) → `data/processed/smap_l4_basin_daily.parquet`. It needs
  `pip install -q h5py` (not installed). Without credentials it prints a skip message and exits 0 (tested); the
  credentialed path is untested.
- IMERG Late/Final V07 daily 2022-2026 could replace POWER rain through the same basin weighting as `p14_imerg.py`
  (not written). Mixing V06 and V07 would need a cross-check.

## 3. GPM IMERG after May 2021 (and full daily IMERG)

- **Error / limit.** The only credential-free IMERG copy is Planetary Computer `gpm-imerg-hhr` (V06 Final), which
  **ends 2021-05-31**. Each Zarr chunk is 12 half-hours of the whole globe (51-57 MB), so a local day is 4 chunks
  (~220 MB) whatever the box size; a full 2016-2021 daily series would be ~430 GB.
- **Workaround.** `pipeline/p14_imerg.py` reads a POWER-ranked storm-day sample: the 6 wettest Mar-Oct days and the
  wettest Nov-Feb day per year, 2016-2021 (38 days, 152 chunks, 8.31 GB, 4.7 min) → `data/processed/imerg_sample.parquet`,
  `imerg_vs_power.json`. On those days POWER and IMERG volumes agree (ratio 1.01, r = 0.62) but POWER compresses extremes
  (OLS slope 0.48), and storm intensity cannot be recovered from POWER daily totals (r = 0.61 in log space). The models
  therefore use daily rain and antecedent wetness, not intensity.
- **Unblock.** §2.

## 4. MODIS 13Q1 gap, July-November 2025 (filled with HLS)

- **Error.** Planetary Computer `modis-13Q1-061` has no MOD13Q1 or MYD13Q1 items after Terra A2025177 (window
  26 Jun-11 Jul 2025) until Terra A2025321 (17 Nov). The first missing composite is Aqua A2025185 (start 2025-07-04), the
  last Aqua A2025313 (start 2025-11-09): 17 windows. A STAC search over Iowa returns 0 items, and a global search for
  Aug-Oct 2025 returns 0. `modis-09A1-061`, `modis-13A1-061`, `modis-43A4-061`, `modis-15A2H-061` and `modis-11A2-061`
  have the same gap; `modis-09Q1-061` has a single h11v04 item. CMR shows the granules exist at LP DAAC (for example
  `MOD13Q1.A2025193.h10v04.061.2025212122128` … `MOD13Q1.A2025305.h11v04.061.2025322130317`), but downloading needs an
  Earthdata login and the LP DAAC host is blocked (§2).
- **Workaround.** NASA HLS v2 gap-fill (`pipeline/p09b_hls_gapfill.py`; PC `hls2-l30` + `hls2-s30`; 7 MGRS tiles;
  1,526 scenes; 0 read failures; ~7 min). HLS composites are built on the MODIS windows and mask and quantile-mapped to
  MODIS NDVI on 2023, 2024 and 2025 overlap windows: living-share bias −0.001, r 0.989, RMSE 0.062; leave-one-year-out
  RMSE 0.086 (fall only 0.132). They fill the 17 windows in `cover_basin_8day` / `cover_basin_daily` with
  `gapfill_src = 'hls'` (HUC-12 level: `cover_hls_huc12_8day.parquet`). Fall 2025 bare share: 0.705 Raccoon, 0.704 Des
  Moines. These values carry the HLS-vs-MODIS calibration error.
- **Unblock.** An Earthdata token plus the `data.lpdaac.earthdatacloud.nasa.gov` host, or a Planetary Computer
  backfill: `p09` then fetches the new items, and MODIS composites automatically take precedence over HLS in those
  windows.

## 5. MODIS tile h10v04 missing for 3 composites

- **Error.** On PC, tile h10v04 (the west ~57% of the Raccoon mask) is missing for MYD13Q1.A2025361 (date 2026-01-04)
  and the two latest composites, MYD13Q1.A2026281 and MOD13Q1.A2026289 (dates 2026-10-16 and 2026-10-24).
- **Workaround.** The rows are kept in `cover_basin_8day` with `tile_cover_frac` 0.43 (Raccoon) / 0.98 (Des Moines) and
  excluded from the daily series when `tile_cover_frac < 0.9`. The Raccoon interpolated series therefore ends 2026-10-05
  (Des Moines 2026-10-20), and the Raccoon as-of value used by the outlook on 2026-11-14 was 27-30 days old (the outlook
  says so). In `cover_huc12_8day` the affected HUC-12 rows have `tile_cover_frac < 0.5` and NaN shares.
- **Unblock.** PC backfill (picked up automatically on re-run).

## 6. HLS: Planetary Computer starts in 2020 and is incomplete for tile 15TUG

- **Limit.** PC `hls2-l30` / `hls2-s30` start 2020-01-01, so there is no HLS for 2016-2019 on PC, and crop year 2020 has
  no Oct-Dec 2019 data. PC holdings for T15TUG are also incomplete: for 2023, NASA CMR lists 85 HLSS30 and 79 HLSL30
  granules with cloud cover ≤ 80, while PC returns 42 S30 and 53 L30 that intersect the focus bbox. PC L30 is thin in
  2020-21 (22-25 granules per year).
- **Workaround.** Everything PC has was used: 591 granules (296 L30, 295 S30), of which 491 had clear focus pixels after
  the Sentinel-2 high-aerosol mask. Median 36 clear observations per field-year for 2021-2026 (10th-90th: 28-48). For
  2016-2019, field leak values reuse each field's 2020-2025 relative cover pattern; the watershed uses MODIS for all
  years.
- **Unblock.** Download the missing granules from LP DAAC with an Earthdata token (§2; download path not implemented).

## 7. CropScape (USDA NASS CDL web service)

- **Error.** `nassgeodata.gmu.edu` is on the allow-list but does not respond (curl exit 000 / empty reply after 0.4 s,
  and again on a 120 s retry).
- **Workaround.** Official national CDL zips from www.nass.usda.gov for 2022-2025
  (`.../Cropland/Release/datasets/<year>_30m_cdls.zip`, 1.7-2.1 GB each, fetched with 6 parallel HTTP range requests and
  deleted after clipping) and Planetary Computer `usda-cdl` for 2011-2021 (PC's CDL ends in 2021). Both are on the same
  30 m grid; pixel alignment was checked (developed-class IoU 0.980 at zero shift vs 0.473 at a 1-pixel shift).
- **Unblock.** Not needed.

## 8. NHD large-scale (high-resolution) flowlines

- **Error.** `GET https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6/query` (layer 6 "Flowline - Large
  Scale"), even with only `where=gnis_name='Raccoon River'&returnCountOnly=true`, returned
  `504 Gateway Timeout ERROR` (CloudFront, "The request could not be satisfied") after 60 s, twice on 2026-11-14.
- **Workaround.** Layer 4 "Flowline - Small Scale" (NHDPlus V2, 1:100k) answers in under 2 s and has the Strahler stream
  order the map needs. `web/data/rivers.geojson` is built from it (37 features after merging and simplifying).
- **Unblock.** Retry later; the map does not need high-resolution lines.

## 9. NASS Quick Stats API key

- **Not a blocker.** No Quick Stats key was needed: crop history and basin crop shares come from the CDL rasters, which
  are bulk downloads (§7). No API key is used anywhere in the app.

## 10. Web hosts for facts (utility, trial and program numbers)

The facts module read original pages on ciww.gov, kcci.com, iowapublicradio.org, nutrientstrategy.iastate.edu,
ars.usda.gov, iowaagriculture.gov, extension.iastate.edu and waterservices.usgs.gov. Result: 52 primary, 2 derived,
9 secondary, 1 unverified (`docs/facts_notes.md`); the fields_model module later appended 3 secondary facts.

| host | error | effect |
|---|---|---|
| nrcs.usda.gov (EQIP booklet) | allowed, but every connection dropped (HTTP/2 INTERNAL_ERROR / empty reply) | EQIP 340 rate (~$74/acre) is `secondary` from a third-party guide; EQIP 328 rate is `unverified` and hidden |
| mymarketnews.ams.usda.gov (fertilizer report) | allowed, connection dropped | AMS anhydrous price `secondary`; ISU's $0.53/lb N (primary) is the low end |
| stories.cals.iastate.edu, crops.extension.iastate.edu, news.iastate.edu | blocked by proxy | ISU "~30 lb N/acre/yr" and STRIPS 72% / 70% stay `secondary` |
| sare.org | blocked by proxy | Kaspar "15-48% at other sites" `secondary` |
| dceg.cancer.gov, PMC (via the facts module) | blocked by proxy | NCI health associations `secondary`; not shown as numbers |
| kdsm17, axios, yahoo | blocked by proxy | Polk County "70-80% from agriculture" `secondary`; not used in the model |
| strips.nrem.iastate.edu | does not resolve from this session | prairie-strip cost $26-33/treated acre and CRP "75% lower" `secondary` |
| opensource.ncsa.illinois.edu (David et al. 2010 PDF) | does not resolve | tile-delivery ratio (McIsaac & Hu) `secondary` |

**Unblock.** Allow-list these hosts and let a verifier re-read the pages; upgrade `verification` in `docs/facts.json`
and re-run `model/m06_strategies.py`, `m07_scenarios.py` and `m08_export_web.py`.

## 11. NASA POWER near-real-time fields

- **Error.** `PRECSNOLAND` is missing (−999) for every cell from **2026-10-01**, and `ALLSKY_SFC_SW_DWN` on 2026-09-07,
  2026-11-10 and 2026-11-11 (the near-real-time GEOS-IT / FLASHFlux period).
- **Workaround.** Left as NaN; nothing filled. Where snowfall is needed (field drainage driver), precipitation counts as
  snow when T2M ≤ 0 °C. The core drivers (PRECTOTCORR, T2M*, GWET*, SNODP) are complete through 2026-11-11. A possible
  level shift between MERRA-2 and GEOS-IT in recent months is not checked (listed as a candidate cause of the 2025-26
  model miss).
- **Unblock.** POWER backfill; re-run `p03_power.py`.

## 12. Not blocked (for the record)

- **NWIS instantaneous-value fill** was not needed: daily values have nitrate and flow through 2026-11-13 at both sites.
  The only recent daily gap (05482000 nitrate, 2026-07-27) has just 32 of 96 IV readings. The IV path runs and filled
  0 days.
- **No mock data is used.** With the files in this repo the app loads only `web/data/`; the mock fallback and its red
  banner exist for development only.
