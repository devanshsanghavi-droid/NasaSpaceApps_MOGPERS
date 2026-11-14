# Module: frontend (web/)

A static app in `web/`, with plain ES modules and no build step. Libraries are vendored and pinned in `web/vendor/`: MapLibre GL JS 4.7.1 and Chart.js 4.4.6. They came from the npm tarballs, with their LICENSE files kept and the `sourceMappingURL` comments removed. The page makes no CDN calls and loads no external tiles. Maps are drawn only from our own GeoJSON on a plain light background.

## Run
```
cd apps/field-to-faucet/web && python3 -m http.server 8731      # open http://localhost:8731/
python3 -I mock/_make_mock.py                                   # (re)write web/mock/* (deterministic, seed 20261114)
node qa/run_qa.cjs http://localhost:8731/                       # Playwright QA + screenshots into web/qa/
```
Routes: `#city` (landing), `#farmer`, `#farmer/<field_id>` (deep link to a field), `#method`.

## Structure
| File | Role |
|---|---|
| `index.html` | Shell: mock banner, tab bar, the three views, footer |
| `css/app.css` | Tokens: ink/ground, one accent (deep teal `#0b5f66`), nitrate red `#c0322b`, sequential warm leak ramp `--leak-0..5`. Breakpoints at 960 and 560 px |
| `js/main.js` | Loads data, renders the views, hash router. Maps are created lazily when their view first shows |
| `js/data.js` | Loader, mock fallback, banner, provenance table, `facts.json` normaliser, field-detail access (single file or split) |
| `js/city.js` | KPI strip, 2025 replay (slider, deltas, chart), river chart, hotspot map and list, 14-day outlook |
| `js/farmer.js` | Field map, field facts, leak calendar and its plain-language sentence, NDVI, priorities, strategy cards and ranking |
| `js/method.js` | Validation tables, sources (NASA tag), caveats, file provenance |
| `js/charts.js` | Chart.js on a linear ms time axis (no date adapter). Draws split shading, the EPA-limit line, a crosshair, and an 8-in-10 band in the tooltip. Nulls are drawn as gaps (`spanGaps:false`) |
| `js/map.js` | Blank-style MapLibre map, HTML-marker labels (no glyph server), context layers, quantile `step` colouring, ramp legend |
| `js/util.js` | Formatting, natural frequencies, small DOM helpers |
| `mock/_make_mock.py` | Writes every mock file and `mock/_manifest.json` |
| `qa/run_qa.cjs` | Playwright QA at 1280 and 375 px |

## How the data maps to the UI
- **KPI strip** (replay year `scenarios.replay.year`, 2025):
  - days above 10: `scenarios.by_year[Y].observed.days_over10`, linked to the USGS site page.
  - plant days: `observed.plant_days`, or else `facts.plant_days_<Y>`.
  - $ cost: `facts.plant_cost_<Y>_usd`, or else `plant_days × thresholds.cost_per_plant_day{lo,hi}`, shown as a range.
  - ban days: `observed.ban_days`, or else `facts.ban_days_<Y>`.
  - people served: `facts.people_served`.
  - Each tile links its source (`facts[*].url` / `thresholds.source`).
- **Replay**:
  - The slider steps through `scenarios.adoption_levels` and opens at 25%.
  - The chart shows `replay.obs`, `replay.base_p50` and `replay.by_level[x]`. The area between the base and scenario lines is shaded as "nitrate kept out of the river".
  - Deltas use `levels[x].avoided.<metric>{p50,lo,hi}` if the exporter adds it. Otherwise they are `levels[0].p50 − levels[x].{p50,hi,lo}`, clamped at 0.
  - Metrics: days_over10, plant_days, cost_usd, ban_days, plus lbN_kept as a sentence.
  - Natural-frequency sentence: observed days minus the delta, over measured days, e.g. "about 1 day in 7".
- **River chart**: `river_series.sites[site].{dates,obs,p10,p50,p90}`.
  - Toggles: site (Raccoon / Des Moines) and range (all / test 2023+ / 2025).
  - `split` drives the shaded "Training / Out-of-time test / Live" periods. `mcl` draws the red dashed line.
- **Hotspot map**: `huc12.geojson`, coloured by `share_of_basin_leak` or `leak_index` in 6 equal-count classes.
  - Popup: name, HUC-12, basin, row_crop_share, poorly_drained_share, bare_days_wet, share_of_basin_leak, rank "of N in basin".
  - The dashed outline is `in_focus`.
  - The side list shows the Raccoon top 6 by `rank`, and their area share against their leak share.
  - Context layers: `basins`, `rivers` (width by `order`), `counties` (optional), `sites`, and `places`. Town labels appear only at zoom ≥ 7.8. `kind: "intake"` places are skipped because sites draw them.
- **Outlook**: the fan is `outlook.{dates,p10,p50,p90}`, anchored at `last_obs` and preceded by 30 days of measured values from `river_series`.
  - `prob_over10` is a 14-cell strip. The headline is the peak probability, phrased as "N in 10".
  - `drivers.*_pctile` become plain-language comparisons with past years.
  - `text` is shown verbatim.
- **Farmer map**: `fields.geojson` squares, coloured by `leak_pctile` in fifths. The focus HUC-12 outlines come from the HUC-12s the fields fall in.
  - "Pick a sample field" cycles through 5 fields from the top tenth by leak percentile, preferring poorly drained ones.
- **Field panel**: `field_detail[id]`, loaded from a single file or from `field_detail/<huc12>.json`.
  - Facts: `leak.lbN_ac_yr{p10,p50,p90}`, drainage, slope, crop_2025, crop sequence chips, and `cover_years`.
  - Leak calendar: the rows are `bare_frac`, `rain_mm`, `storm_days`, `wetness`, and `leak_risk`, each shaded within its own row.
  - The riskiest 3-month window (by summed `leak_risk`) is outlined, and the sentence is built from it: average bare share, the window's share of storm days, and whether peak wetness falls inside it.
  - NDVI comes from `ndvi_recent`, with a 0.30 living-cover line.
- **Strategy cards**: text from `strategies.json`, field numbers from `field_detail.strategies[S].{lbN_kept_ac,fert_value_usd_ac}`.
  - If the field numbers are missing, lb kept is estimated as `n_loss_reduction × field leak`, and the card says so.
  - Each card shows why, evidence (trials and `satellite_evidence`), lb N kept with range and an interval bar on a shared axis, fertilizer value, cost, yield risk, soil health, gaps, local-review risks, and who pays (with links).
- **Ranking** (shown under "How we rank"): each goal is min-max scaled to 0–1 across S0..S3. Score = Σ(weight × goal score) / Σ weights, with weights 0–3 from the sliders (default 2, 2, 1, 1). The goals:
  - nitrogen kept: lbN_kept p50.
  - yield safety: `yield_risk` level, low 1 / medium 0.5 / high 0.
  - soil: `soil_score`, or else the count of `soil_health` items.
  - low net cost: −(cost midpoint − fertilizer value p50).
- **Method**: `validation.json`, `meta.sources` (NASA badge), `meta.caveats`, and a per-file provenance table.

## Mock fallback
1. `data.js` reads the `python -m http.server` directory listing of `data/` and `mock/_manifest.json`, so a missing file is never requested and the console shows no 404s. On `*.github.io` there is no listing, so each `data/` file is requested directly.
2. Each contract file loads from `data/<file>`. If it is missing, `mock/<file>` is used and the file is recorded as `mock`. A `data/` file with a top-level `"mock": true` also counts as mock.
3. **Partial case:** when the real `huc12.geojson` has outlines but no `leak_index` (true today), the scores are taken from `mock/huc12.geojson` by huc12 id. That file is reported as "huc12.geojson (leak scores)".
4. `field_detail` must come from the same place as `fields`. Real fields with no real detail show "not exported yet"; the panel never shows mock detail for real fields.
5. A red sticky **"MOCK DATA — not real"** banner names every mock file. Every section that draws mock values also carries a small red `MOCK` chip. Every mock text string starts with "MOCK".

## Still mock (as of this build)
`meta.json`, `river_series.json`, `validation.json`, `scenarios.json`, `outlook.json`, `fields.geojson`, `field_detail` (split, 9 HUC-12s, 1,338 fields), `strategies.json`, `facts.json`, and the HUC-12 leak scores.

Real today: `basins.geojson`, `huc12.geojson` (outlines), `sites.json`, `rivers.geojson`, `places.json`, `counties.geojson`.

Mock focus area: 9 Raccoon HUC-12s around Jefferson/Scranton (071000061401-05, 071000061004, 071000061301, 071000070101, 071000070103). The real focus area comes from the fields module.

## Contract interpretations (exporters: please match or tell frontend)
- `facts.json` is not in the web contract, but the KPI strip needs it. The app reads `web/data/facts.json` as `{facts:{<key>:{value,unit,label,source,url,verified}}}` (a list of `{id,...}` also works). Keys used: `people_served`, `plant_days_<Y>`, `plant_cost_<Y>_usd`, `ban_days_<Y>`, `fert_price_usd_lb_N`.
- `scenarios.levels[].<metric>` is read as the absolute modelled value at that adoption level. Ranges of differences cannot be derived exactly from marginal ranges, so please add `avoided:{days_over10:{p50,lo,hi}, plant_days, cost_usd, ban_days, lbN_kept}` per level; the app prefers it when present.
- `scenarios.by_year[Y].observed` has no `cost_usd`; the cost comes from facts, or from plant days × cost per plant day.
- `strategies[].yield_risk`: a string that starts with Low/Medium/Moderate/High, or `{level, text}`.
- Optional extra: `soil_score` (0–1) for ranking.
- `validation.json`: `{splits, sites:{<site>:{name, by_split:{test:{gbm:{NSE,KGE,RMSE,MAE,coverage80,CSI,...}, climatology:{...}, persistence_7d:{...}}}}}, lines:[...], crisis_2025:{text}}`. The raw `metrics.json` shape `{<site>:{<split>:{<model>:{...}}}}` also renders.
- `places.json`: a top-level array. `kind` (`city` / `town` / `intake`) is used for label styling and zoom gating.
- `outlook.drivers.*_pctile` is read as the percentile against past years for the same time of year (0–100).
- `field_detail.calendar.wetness` is read on a 0–1 scale. `leak_risk` is 0–1.

## QA (`qa/run_qa.cjs`)
The script runs at 1280×860 and 375×760. It loads City, moves the replay slider (and checks the deltas change), toggles the river site and range, and opens a hotspot popup. On Farmer it picks a sample field (checks ≥ 4 cards), changes priorities (checks the top card changes), clicks the map, and checks the hash deep link. It also loads Method.

It asserts no console errors or warnings, no failed or ≥ 400 requests, and no horizontal scroll. Result: **QA OK**.

The default headless GL backend in this container logs "GL Driver Message … GPU stall due to ReadPixels" while compositing the WebGL canvas. That message comes from the browser, not from page code. The script launches with `--use-angle=swiftshader`, which removes it, so the check stays strict. Screenshots are saved to `web/qa/*.png` and quantised to 128 colours to keep them small.
