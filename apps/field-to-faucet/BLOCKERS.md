# Blockers and workarounds

Each module appends a section: what failed (exact error), what we used instead, and what would unblock it.

## Network policy (orchestrator, 2026-11-14)
- The cloud container's default network policy blocked every data host (`403` on CONNECT for waterservices.usgs.gov,
  planetarycomputer.microsoft.com, power.larc.nasa.gov, hydro.nationalmap.gov, ...). Fixed by creating an environment
  with an explicit allow-list (see CONTRACTS.md, "Network"). Hosts not on that list are still blocked.
- `nassgeodata.gmu.edu` (CropScape) is allowed but does not respond (curl exit 000 / empty reply after 0.4 s and on
  120 s retry). Workaround: official national CDL zips from www.nass.usda.gov for 2022-2025.
