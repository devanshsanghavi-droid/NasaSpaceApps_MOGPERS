# hazard module blockers

- **GPM IMERG not used.** The IMERG Zarr storage host is not reachable from this environment (see CONTRACTS.md, Network).
  Precipitation is NASA POWER `PRECTOTCORR` instead, which POWER's parameter metadata describes as MERRA-2
  bias-corrected total precipitation. No IMERG request was attempted in this module.
- No other blockers. All 424 NASA POWER cells and all 364 USDM requests (7 states x 26 years x 2 endpoints) succeeded.
