# Data access notes

These were verified on 2026-11-14 from a laptop. The cloud environment may block some hosts, so test first.

## No login needed
- **Microsoft Planetary Computer STAC:** `pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1", modifier=planetary_computer.sign_inplace)`
  - **hls2-l30, hls2-s30:** Harmonized Landsat Sentinel-2, 30 m COGs (cloud-optimized GeoTIFFs) with overviews 2/4/8/16. One band at overview level 2 (60 m) reads in about 5-8 s. Fmask bits 1-4 mean cloud, adjacent cloud, cloud shadow and snow.
  - **usda-cdl:** Cropland Data Layer. Filter with `query={"usda_cdl:type":{"eq":"cropland"}}`. EPSG:5070, 30 m.
  - **gnatsgo-rasters:** gridded soils, 10 m. Includes mukey, aws0_100, soc0_30, nccpi3corn/soy, droughty and rootznaws. The same data is also available as **gnatsgo-tables**.
  - **nasadem:** NASA's reprocessed SRTM elevation data.
  - **gpm-imerg-hhr:** GPM IMERG half-hourly precipitation as Zarr. Open with `use_cftime=True`; the variable is `precipitationCal`.
  - **nasa-nex-gddp-cmip6:** NASA NEX-GDDP-CMIP6 climate projections.
  - **modis-13Q1-061:** MODIS vegetation indices (NDVI/EVI), 250 m.
  - **modis-16A3GF-061:** MODIS annual evapotranspiration, 500 m.
  - Also available: modis-11A2-061 (land surface temperature), era5-pds, gridmet, terraclimate, daymet, landsat-c2-l2, sentinel-2-l2a.
  - SAS signing tokens expire. Re-sign item URLs if reads start returning 403.
- **NASA POWER daily point API:** `https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M,PRECTOTCORR,GWETROOT,...&community=AG&longitude=..&latitude=..&start=YYYYMMDD&end=YYYYMMDD&format=JSON`
- **USDA Soil Data Access (SQL):** POST to `https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest` with `data={"query": SQL, "format": "JSON+COLUMNNAME"}`.
- **NASA CMR search:** works for finding granules. Downloading SMAP, ECOSTRESS, GRACE or NLDAS needs an Earthdata login, which we do not have yet.
- **NASS QuickStats:** the API needs a key. Instead, stream the public bulk file `qs.crops_YYYYMMDD.txt.gz` (listed at https://www.nass.usda.gov/datasets/) and filter rows as they arrive. `shared/central_iowa_pipeline/pipeline/context_nass.py` already does this.
- **County boundaries:** the Census cartographic boundary file https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip

## Needs login or key (keep behind a flag, never commit credentials)
- **Earthdata login (free):** SMAP, ECOSTRESS, GRACE-FO mascons, NLDAS/GLDAS. Access them through `earthaccess` plus a `~/.netrc` file.
- **OpenET API key (free sign-up).**
- **Alternatives that skip the login:**
  - **GRACE-based groundwater drought indicators:** https://nasagrace.unl.edu (University of Nebraska / NASA), which may offer direct GeoTIFF downloads.
  - **USGS SSEBop evapotranspiration:** https://earlywarning.usgs.gov/ssebop

## Timed out from the laptop
- modis.ornl.gov
- open-meteo
- USGS EPQS elevation service (intermittent)

## Reusable code
`shared/central_iowa_pipeline/` holds working fetchers for central Iowa (HLS tile 15TVG). `notes/*.md` explains each one.

| Script(s) | Fetches |
|---|---|
| cdl_* | Cropland Data Layer crop history |
| conf_* | soils, terrain (NASADEM), NASA POWER weather and IMERG storm data |
| context_* | NASS yields, county boundaries and NEX-GDDP-CMIP6 climate |
| hls_* | HLS time series |
| evidence_* | trial evidence priors and US Drought Monitor data |

`shared/evidence/evidence_priors.json` collects literature effect sizes from trials, covering cover crops, no-till, prairie strips, extended rotations and nitrate, with citations.
