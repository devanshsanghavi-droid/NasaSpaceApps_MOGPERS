"""geo module: per-survey-area SSURGO aggregates from USDA Soil Data Access (SQL), cached to data/raw/sda/.

For each of the 7 states, one SQL call aggregates muaggatt (aws0100wta, aws0150wta; cm of water) over map units
(mapunit.muacres) per survey area (legend.areasymbol). Rows are cached as JSON in data/raw/sda/aws_<ST>.json.
Optionally (if the server allows) also NCCPI v3 (all crops) from cointerp, component-weighted per map unit.

Run: /home/user/venv-db/bin/python pipeline/geo_soils_fetch.py [--refresh]
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "sda"
RAW.mkdir(parents=True, exist_ok=True)
URL = "https://sdmdataaccess.sc.egov.usda.gov/Tabular/post.rest"
UA = {"User-Agent": "drought-bill-hackathon"}
STATES = ["IA", "NE", "KS", "MO", "IL", "SD", "MN"]

AWS_SQL = """
SELECT l.areasymbol, l.areaname, l.areaacres, l.saverest,
  SUM(mu.muacres) AS mu_acres,
  SUM(CASE WHEN ma.aws0100wta IS NOT NULL THEN mu.muacres ELSE 0 END) AS acres_aws100,
  SUM(ma.aws0100wta * mu.muacres) AS aws100_x_acres,
  SUM(CASE WHEN ma.aws0150wta IS NOT NULL THEN mu.muacres ELSE 0 END) AS acres_aws150,
  SUM(ma.aws0150wta * mu.muacres) AS aws150_x_acres,
  COUNT(*) AS n_mapunits
FROM legend l
JOIN mapunit mu ON mu.lkey = l.lkey
LEFT JOIN muaggatt ma ON ma.mukey = mu.mukey
WHERE l.areasymbol LIKE '{st}%' AND l.areatypename = 'Non-MLRA Soil Survey Area'
GROUP BY l.areasymbol, l.areaname, l.areaacres, l.saverest
ORDER BY l.areasymbol
"""

# NCCPI v3 (National Commodity Crop Productivity Index, all crops 0-1) per map unit: component-percent weighted
# mean of cointerp.interphr for the top-level rule, then muacres-weighted per survey area.
NCCPI_SQL = """
SELECT l.areasymbol,
  SUM(CASE WHEN x.nccpi IS NOT NULL THEN mu.muacres ELSE 0 END) AS acres_nccpi,
  SUM(x.nccpi * mu.muacres) AS nccpi_x_acres
FROM legend l
JOIN mapunit mu ON mu.lkey = l.lkey
LEFT JOIN (
  SELECT c.mukey, SUM(ci.interphr * c.comppct_r) / NULLIF(SUM(c.comppct_r), 0) AS nccpi
  FROM component c
  JOIN cointerp ci ON ci.cokey = c.cokey
  WHERE ci.mrulename = 'NCCPI - National Commodity Crop Productivity Index (Ver 3.0)'
    AND ci.ruledepth = 0 AND ci.interphr IS NOT NULL
    AND c.mukey IN (SELECT mu2.mukey FROM mapunit mu2 JOIN legend l2 ON l2.lkey = mu2.lkey
                    WHERE l2.areasymbol LIKE '{st}%')
  GROUP BY c.mukey
) x ON x.mukey = mu.mukey
WHERE l.areasymbol LIKE '{st}%' AND l.areatypename = 'Non-MLRA Soil Survey Area'
GROUP BY l.areasymbol
ORDER BY l.areasymbol
"""


def run_sql(sql, tries=3):
    for k in range(tries):
        try:
            r = requests.post(URL, data={"query": sql, "format": "JSON+COLUMNNAME"}, headers=UA, timeout=600)
            r.raise_for_status()
            t = r.json().get("Table", [])
            return [dict(zip(t[0], row)) for row in t[1:]] if t else []
        except Exception as e:  # noqa: BLE001
            print("  SDA error:", repr(e)[:300], flush=True)
            time.sleep(5 * (k + 1))
    raise RuntimeError("SDA query failed")


def main():
    refresh = "--refresh" in sys.argv
    for kind, sql in (("aws", AWS_SQL), ("nccpi", NCCPI_SQL)):
        for st in STATES:
            f = RAW / f"{kind}_{st}.json"
            if f.exists() and not refresh:
                continue
            t0 = time.time()
            try:
                rows = run_sql(sql.format(st=st))
            except RuntimeError as e:
                print(kind, st, "FAILED", e, flush=True)
                continue
            f.write_text(json.dumps({"query": sql.format(st=st), "url": URL, "fetched": time.strftime("%Y-%m-%d"),
                                     "rows": rows}))
            print(kind, st, len(rows), "rows", f"{time.time()-t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
