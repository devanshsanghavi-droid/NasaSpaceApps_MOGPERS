# Blockers

Data sources we could not reach (or could only partly use) from the build environment, the exact error, what would unblock them,
and the real alternative we used. Consolidated from the rows each module appended; nothing was dropped. Module notes (`notes/*.md`)
have the full details.

## 1. Access blocked: source not used

| Source | Host | Error | Unblock with | Alternative used | Found by |
|---|---|---|---|---|---|
| GRACE/GRACE-FO mascons (JPL, via PO.DAAC) | podaac / urs.earthdata.nasa.gov; grace.jpl.nasa.gov | No Earthdata login in this environment; hosts blocked | Free Earthdata login + `~/.netrc`, then `WATER_CLOCK_EARTHDATA=1 python3 pipeline/nasa_grace_gfz.py` (`earthaccess` code path, short name TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4) | GFZ GravIS RL06 TWS + G3P groundwater; GRACE-DA percentiles (nasagrace.unl.edu) | nasa |
| CSR GRACE RL06.3 mascons | download.csr.utexas.edu | TLS verification fails: server chain ends at emSign Root CA - G1, not in the container trust store (TLS verification was not disabled) | Run from a machine whose trust store holds emSign Root CA - G1 | GFZ GravIS and GRACE-DA | nasa |
| OpenET field-scale ET (NASA-supported) | OpenET API | No API key | Free OpenET key | MODIS MOD16A3GF ET (relative check) + WIMAS reported water per crop + NASA POWER FAO-56 reference ET | nasa-land |
| KGS High Plains section-level database (bedrock elevation / saturated thickness per section) | hercules.kgs.ku.edu (same path on geohydro.kgs.ku.edu = HTTP 404) | Proxy 403 | Allowlist hercules.kgs.ku.edu | USGS OFR 98-393 base-of-aquifer contours + KGS WIZARD depth-to-bedrock picks; USGS SIR 2012-5177 2009 saturated thickness for cross-check. Cost: about +/-22 ft base uncertainty per field | wells |
| KGS WIZARD legacy query hosts | hercules.kgs.ku.edu, abyss.kgs.ku.edu, chasm.kgs.ku.edu | Proxy 403 | Allowlist the hosts | geohydro.kgs.ku.edu WIZARD and USGS Water Data API | wells |
| NASS QuickStats API | quickstats.nass.usda.gov | Needs an API key; host also blocked | Free key + allowlist | NASS QuickStats bulk files from www.nass.usda.gov/datasets | econ |
| USDA AMS Market News | mymarketnews.ams.usda.gov | Host blocked; API needs a key | Key + allowlist | NASS prices received (bulk file) | econ |
| KSU AgManager farm management guides (irrigated vs dryland budgets) | www.agmanager.info | `curl: (56) CONNECT tunnel failed, response 403` (proxy) | Allowlist www.agmanager.info | ERS Commodity Costs and Returns, Prairie Gateway (no irrigated/dryland split; no pumping energy cost) | econ |
| BEA Regional county earnings (CAINC5N farm earnings share) | apps.bea.gov, www.bea.gov | `curl: (56) CONNECT tunnel failed, response 403` (proxy) | Allowlist apps.bea.gov | `share_of_economy_from_irrigated_ag = null`; Census of Agriculture 2022 crop sales, irrigated acres, sales per resident instead | econ |
| KGS ArcGIS hub / services (official GMD boundary layer) | kgs-gis-data-and-maps-ku.hub.arcgis.com, services.kgs.ku.edu | `curl: (56) CONNECT tunnel failed, response 403` (proxy); www.kgs.ku.edu/Hydro/gmd.html has no polygon download | Allowlist the KGS GIS hub | GMD polygons from USGS ScienceBase data release 577b8b5fe4b0ef4d2f4223a1 (Kansas irrigation water-use analysis regions = the 5 GMDs + 3 regions) | econ |
| Outside-fact pages for CLAIMS.md (NASA/JPL PIA16840, K-State Steward et al. release, Kansas news on the governor's 2025 speech) | www.jpl.nasa.gov, www.k-state.edu, thebeaconnews.org | WebFetch: `getaddrinfo ENOTFOUND` (host not allowed in this session) | Allow the hosts, or check the pages by hand | Web search summaries (marked "unverified, search-corroborated" in CLAIMS.md); KGS pages on www.kgs.ku.edu opened directly | docs |

## 2. Access worked around: same data from another host or route

| Source | Host | Error | Unblock with | Route used | Found by |
|---|---|---|---|---|---|
| KGS WIZARD download files | maps.kgs.ku.edu | Proxy CONNECT 403 on the sites/wlevel CSV links from wizarddownload.cfm | Allowlist maps.kgs.ku.edu | Identical files from https://geohydro.kgs.ku.edu/geohydro/downloads/ | wells |
| WIMAS download files and long queries | maps.kgs.ku.edu; geohydro.kgs.ku.edu | Proxy CONNECT 403 on wimas_/qty_/wuse_ download links; long single 1990-2025 wuse queries for large counties dropped by the proxy (`RemoteDisconnected`) | Allowlist maps.kgs.ku.edu | Same files from https://geohydro.kgs.ku.edu/geohydro/downloads/; wuse queries split into year windows | pumping |
| USGS NWIS legacy gwlevels service | waterservices.usgs.gov/nwis/gwlevels (redirects to waterdata.usgs.gov) | HTTP 301 to a decommission notice (api-decom-fall-2025); waterdata.usgs.gov refused by proxy | None needed | USGS Water Data OGC API, api.waterdata.usgs.gov/ogcapi/v0 field-measurements | wells |
| TerraClimate Zarr (anonymous) | cpdataeuwest.blob.core.windows.net | HTTP 409 "Public access is not permitted on this storage account" | n/a | Same Zarr through the Planetary Computer STAC SAS token (needs `adlfs`) | nasa |
| GPM IMERG half-hourly Zarr (annual totals) | Planetary Computer gpm-imerg-hhr (ai4edataeuwest) | Not an access error: the Zarr ends 2021-05-31 and is chunked 12 half-hours x full globe (~55 MB/chunk), so one point-year needs ~80 GB | Earthdata login for GPM_3IMERGM monthly | IMERG daily via NASA POWER (`IMERG_PRECTOT`, UTC days only); PC Zarr used for a 4-day cross-check | nasa |
| USDA CDL on Planetary Computer | landcoverdata (usda-cdl) | Not an error: collection stops at 2021 | n/a | 2022-2024 from the NASS national CDL zips (byte-range download) | nasa-land |

## 3. Data gaps in sources we used

| Source | Host | Gap and error | Unblock with | Handling | Found by |
|---|---|---|---|---|---|
| GRACE-DA weekly files, October 2025 | nasagrace.unl.edu | HTTP 404 for `/data/20251006/GRACEDADM_CLSM0125US_7D.A20251006.030.nc4` and the other Oct-2025 weekly files (listed on ConusData.aspx but not served); 2025-11-03 also 404 (replaced by 2025-11-17) | Retry later / ask UNL NDMC | Month left empty in `grace_region.parquet` (GFZ TWS row still present) | nasa |
| WIMAS water use, Sherman County (20181), use year 1998 | geohydro.kgs.ku.edu/geohydro/wimas/wuse_trends.cfm | HTTP 500 "Error Executing Database Query" for any window containing 1998 (also township 9S alone); other years fine | Ask KGS/DWR to fix the record, or request the 1998 Sherman file from KDA-DWR | Left null (`complete=False`) in `wimas_county_year`; all other 935 county-years present | pumping |
| NASS county irrigated / non-irrigated yields | www.nass.usda.gov (bulk) | Not published after 2018 (corn), 2009 (county irrigated sorghum); many suppressed county all-practice years after 2008 | None (NASS stopped publishing) | Irrigated/dryland yields = county all-practice yield x 2000-2018 county practice ratio; state yield where missing | econ, model |
| NASS agricultural-district rows for our region | www.nass.usda.gov (bulk) | `nass_county.parquet` holds districts `20D10` (Northwest), `20D40` (North Central) and `20D70` (Northeast). The parquet labels are correct, but `notes/econ.md` calls 20D40/20D70 "West Central"/"Southwest". The West Central (ASD 20) and Southwest (ASD 30) districts that hold most of our counties were not extracted | Re-run `pipeline/econ_nass_process.py` keeping ASD 20 and 30 | Model used only county and state rows (no district fallback) | model (found), econ (owner) |
| Town public-supply wells | - | Not linked to the clock (no verified well-to-town mapping) | KDHE / KDA public water supply well locations | `town_note` says "not verified"; no town clock is claimed | econ, model |
