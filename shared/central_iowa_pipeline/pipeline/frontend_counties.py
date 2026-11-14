"""Copy the real county outlines (data/counties.geojson, context module) to web/data/counties.geojson.

counties.geojson is not in the web contract, but the map draws it. The app loads web/data/ first and
falls back to an approximate mock in web/mock/. Outlines only (name, fips); no estimates.

Run:  .venv/bin/python pipeline/frontend_counties.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "counties.geojson"
DST = ROOT / "web" / "data" / "counties.geojson"


def main() -> None:
    gj = json.loads(SRC.read_text())
    feats = []
    for ft in gj.get("features", []):
        pr = ft.get("properties") or {}
        geom = ft.get("geometry") or {}
        if not pr.get("name") or not pr.get("fips") or geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise SystemExit(f"unexpected feature in {SRC}: {pr}")
        keep = {k: pr[k] for k in ("name", "fips", "state_abbr", "frac_in_tile") if k in pr}
        feats.append({"type": "Feature", "properties": keep, "geometry": geom})
    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(json.dumps({"type": "FeatureCollection", "source": "data/counties.geojson (US Census cartographic boundary counties 2023, via context module)",
                               "features": feats}, separators=(",", ":")))
    print(f"wrote {DST.relative_to(ROOT)}: {len(feats)} counties ({DST.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
