# NASA Space Apps 2026: Field Shift (team MOGPERS)

Three concepts are being built in parallel, one per branch, for the challenge **"Field Shift: Adapting Farms with NASA Data"** (see `docs/CHALLENGE.md`). Each one leads with an impact that judges can grasp in seconds.

| Branch | Concept | Headline impact |
|---|---|---|
| `field-to-faucet` | Field to Faucet | Which farm rotations upstream decide whether 600,000 people in Des Moines can use their tap water during nitrate spikes |
| `water-clock` | Water Clock | Years of irrigation water left under each western Kansas field, and how many years a rotation buys back |
| `drought-bill` | Drought Bill | Each county's and farm's expected drought loss in dollars, and how much a more diverse rotation cuts it |

## Repo map
- **`docs/CHALLENGE.md`:** the challenge brief, the listed resources and the judging criteria.
- **`docs/concepts/*.md`:** the spec for each concept.
- **`docs/BUILD_RULES.md`:** shared rules: real data only, a claims register, deliverables.
- **`docs/DATA_ACCESS.md`:** which data sources work without login, and how.
- **`docs/research/`:** earlier concept research, including the COUNTERFIELD causal design and its red-team review.
- **`shared/central_iowa_pipeline/`:** working data fetchers for central Iowa (HLS, CDL, soils, NASADEM, NASA POWER, IMERG, NEX-GDDP-CMIP6, NASS).
- **`shared/evidence/evidence_priors.json`:** literature effect sizes from trials, with citations.
