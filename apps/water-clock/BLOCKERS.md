# Blockers

Data sources that could not be reached from the build environment, with the error and what would unblock them.

| Source | Host | Error | Unblock with | Alternative used |
|---|---|---|---|---|
| GRACE/GRACE-FO mascons (JPL, PO.DAAC) | podaac / urs.earthdata.nasa.gov | No Earthdata login in this environment | Free Earthdata login + ~/.netrc, then `earthaccess` (code path behind a flag) | GFZ GravIS and nasagrace.unl.edu GRACE-DA |
| CSR GRACE RL06.3 mascons | download.csr.utexas.edu | TLS verification fails: server chain ends at emSign Root CA - G1, which is not in the container trust store | Run from a machine whose trust store holds emSign Root CA - G1 | GFZ GravIS and GRACE-DA |
| KGS WIZARD legacy query hosts | hercules.kgs.ku.edu, abyss.kgs.ku.edu, chasm.kgs.ku.edu | Proxy 403 (not allowed in this environment) | Add the hosts to the environment allowlist | geohydro.kgs.ku.edu WIZARD and USGS NWIS |
| NASS QuickStats API | quickstats.nass.usda.gov | Needs an API key; host also blocked | Free key | NASS bulk file from www.nass.usda.gov/datasets |
| USDA AMS Market News | mymarketnews.ams.usda.gov | Host blocked; API needs a key | Key + allowlist | NASS prices received (bulk file) |
| OpenET | openet API | No API key | Free OpenET key | MODIS MOD16A3GF ET + NASA POWER FAO-56 reference ET |
| KGS WIZARD download file host | maps.kgs.ku.edu | Proxy CONNECT 403 on the sites/wlevel CSV links from wizarddownload.cfm | Allowlist maps.kgs.ku.edu | Same files fetched from https://geohydro.kgs.ku.edu/geohydro/downloads/ (identical path) |
| USGS NWIS legacy gwlevels service | waterservices.usgs.gov/nwis/gwlevels (redirects to waterdata.usgs.gov) | 301 to a decommission notice (api-decom-fall-2025); waterdata.usgs.gov refused by proxy | None needed | USGS Water Data OGC API api.waterdata.usgs.gov/ogcapi/v0 field-measurements |
| KGS High Plains section-level database (bedrock elevation / saturated thickness per section) | hercules.kgs.ku.edu (geohydro.kgs.ku.edu same path = 404) | Proxy 403 | Allowlist hercules.kgs.ku.edu | USGS OFR 98-393 base-of-aquifer contours + KGS WIZARD depth-to-bedrock picks; USGS SIR 2012-5177 2009 saturated thickness for cross-check |
| GRACE-DA weekly file, Oct 2025 | nasagrace.unl.edu | HTTP 404 for /data/20251006/GRACEDADM_CLSM0125US_7D.A20251006.030.nc4 and the other Oct-2025 weekly files (listed on ConusData.aspx but not served) | Re-try later / ask UNL NDMC | Month left empty in grace_region.parquet (GFZ TWS row still present) |
| GPM IMERG half-hourly Zarr (annual totals) | Planetary Computer gpm-imerg-hhr (ai4edataeuwest) | Not an access error: Zarr ends 2021-05-31 and is chunked 12 half-hours x full globe (~55 MB/chunk), so one point-year needs ~80 GB | Earthdata login for GPM_3IMERGM monthly | IMERG daily via NASA POWER (IMERG_PRECTOT, UTC); PC Zarr used only for a 4-day cross-check |
| TerraClimate zarr (anonymous) | cpdataeuwest.blob.core.windows.net | HTTP 409 "Public access is not permitted on this storage account" | n/a | Same zarr via Planetary Computer STAC SAS token (works; needs adlfs) |
| WIMAS water-use query, Sherman County (20181) use year 1998 | geohydro.kgs.ku.edu/geohydro/wimas/wuse_trends.cfm | HTTP 500 "Error Executing Database Query" for any window containing 1998 (also township 9S alone); other years fine | Ask KGS/DWR to fix the record, or request the 1998 Sherman water-use file from KDA-DWR | Sherman 1998 left null (complete=False) in wimas_county_year; all other 935 county-years present |
| WIMAS download file host | maps.kgs.ku.edu | Proxy CONNECT 403 on wimas_/qty_/wuse_ download links; long single 1990-2025 wuse queries for large counties dropped by the proxy (RemoteDisconnected) | Allowlist maps.kgs.ku.edu | Same files from https://geohydro.kgs.ku.edu/geohydro/downloads/; wuse queries split into year windows |
