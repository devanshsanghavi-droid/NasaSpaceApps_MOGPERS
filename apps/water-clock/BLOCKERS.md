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
