# sat module blockers

1. **MODIS July-August 2025 is missing on Planetary Computer.** `modis-13Q1-061` has no Terra (MOD13Q1) composites
   between DOY 177 and DOY 321 of 2025, and no Aqua (MYD13Q1) composites between DOY 169 and DOY 329 (checked
   2026-11-14). The same gap shows in `modis-13A1-061`, `modis-09A1-061` and `modis-15A2H-061`. The 2026 composites are
   there, so this looks like an ingestion gap. As a result, every 2025 row in `modis_county_year.parquet` is null
   (n_composites = 0). Fix: get MOD13Q1 2025 from NASA LP DAAC / Earthdata, which needs a login we do not have, or
   re-check PC later.
2. **MOD13Q1 2024 DOY 225 (composite starting 12 Aug 2024) is missing on PC** for all 6 tiles. 2024 uses 3 composites
   (DOY 193, 209, 241). From 2001-2023, dropping DOY 225 changes county NDVI by -0.004 on average (sd 0.008).
   So 2024 is probably biased low by about 0.004 NDVI, roughly 3-5 VCI points. We did not adjust it.
3. **NASA NCCS THREDDS (ds.nccs.nasa.gov) is blocked by the proxy (403).** The reference script
   (`shared/central_iowa_pipeline/pipeline/context_climate.py`) subset NEX-GDDP-CMIP6 on that server. Without it,
   `sat_cmip6.py` reads the PC blob copies. Each daily chunk covers the whole globe, so each variable-year costs
   45-70 MB of transfer for a box of about 60 x 72 cells. At about 3 MB/s this is the reason years are subsampled
   (every other year, 10 per period).
4. **MODIS land cover (MCD12Q1) is not on Planetary Computer**, so there was no NASA cropland mask. We built the crop
   mask from USDA CDL 2016 instead, using the cdl module's cached 240 m lattice.
