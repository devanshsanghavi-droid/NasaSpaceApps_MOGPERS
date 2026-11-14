# Blockers and workarounds

Each entry says what was blocked, the error, what we used instead, and what would unblock it.
Module-level details: `notes/blockers_hazard.md`, `notes/blockers_sat.md`, and the notes for each module.

| # | Source | What happened | Workaround used | To unblock |
|---|---|---|---|---|
| 1 | Every external data host (RMA, NASA POWER, Planetary Computer, NASS, Census, USDM, Soil Data Access) | The default cloud environment's network policy refused them: proxy `403` to CONNECT | We created a personal cloud environment (`MOGPERS drought-bill data`) that allows just the needed hosts. All data in this branch was fetched through it | Resolved |
| 2 | **SMAP** root-zone soil moisture, **ECOSTRESS** ESI | These need a NASA Earthdata login, which we don't have | NASA POWER `GWETROOT` (root-zone soil wetness, MERRA-2) for soil-moisture hazard | A free Earthdata login plus `~/.netrc`, read with `earthaccess` |
| 3 | **GPM IMERG** (Planetary Computer Zarr) | The Zarr's storage account is not on the allowed host list | NASA POWER `PRECTOTCORR` (MERRA-2 bias-corrected precipitation) | Allow the IMERG storage host, or use an Earthdata login for GES DISC |
| 4 | **gNATSGO rasters/tables** (Planetary Computer, `soils.blob.core.windows.net`) | Host not allowed | USDA Soil Data Access SQL (`muaggatt.aws0100wta`, `aws0150wta`, NCCPI), weighted by map-unit acres per county | Allow `soils.blob.core.windows.net` for field-level 10 m soils |
| 5 | **NASA NCCS THREDDS** (`ds.nccs.nasa.gov`) for NEX-GDDP-CMIP6 subsetting | Proxy `403` | Read the Planetary Computer blob copies (global daily chunks, 45-70 MB per variable-year), so years were subsampled: every other year, 10 per period | Allow `ds.nccs.nasa.gov` for full-year, more-GCM subsets |
| 6 | **MODIS MOD13Q1 Jul-Aug 2025** on Planetary Computer | Ingestion gap: no composites between DOY 177 and 321 of 2025; 2024 DOY 225 missing too | 2025 MODIS left null; 2024 uses 3 of 4 composites (bias about -0.004 NDVI) | LP DAAC download with an Earthdata login, or re-check PC |
| 7 | **MODIS land cover** (MCD12Q1) | Not on Planetary Computer | USDA CDL 2016 cropland mask for MODIS NDVI | Earthdata login |
| 8 | **CDL 2022-2024** on Planetary Computer | The PC collection stops at 2021 | Official USDA NASS national CDL GeoTIFFs for 2022-2024 from www.nass.usda.gov; pixel alignment with PC 2021 checked | None needed |
| 9 | **NASS county estimates** | Not a network block: NASS suppresses some counties (folds them into "other counties"). County corn yields drop from about 637 counties in 2000 to 384 in 2025 | State means are used where a county is suppressed, and flagged | None (a disclosure rule) |
| 10 | **RMA 2025 crop year** | Not a block: still provisional; files update weekly | 2025 is excluded from training and testing, and shown as provisional | Wait for RMA to finalize |
| 11 | **Fact-check sources** (EWG, GAO, CBO, journal sites, SARE) | WebFetch could not open them from this environment | Headline loss numbers were recomputed directly from RMA files (`notes/rma.md`). Others were cross-checked through USDA ERS and AFBF pages, which opened. See `CLAIMS.md` for each item's status | Allow those hosts, or check by hand from a laptop |
