"""Fetch USGS groundwater-level field measurements for the region counties.

The legacy endpoint https://waterservices.usgs.gov/nwis/gwlevels/ now answers 301 -> a decommission
notice (waterdata.usgs.gov/blog/api-decom-fall-2025/#gwlevels, host refused by the session proxy), so we use
the USGS Water Data OGC API (verified 2026-11-14, api-version 0.82.2):
  https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items
     ?f=json&state_code=20&county_code=XXX&parameter_code=72019&limit=10000
  (72019 = depth to water level, ft below land surface)
  https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items
     ?f=json&state_code=20&county_code=XXX&site_type_code=GW&limit=10000
Raw JSON cached in data/raw/nwis/<fips>_{fm,ml}_<page>.json.
"""
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

from wells_kgs_fetch import COUNTIES

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "nwis"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "water-clock-hackathon"}
API = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/"
FM_PROPS = ("monitoring_location_id,parameter_code,value,unit_of_measure,time,qualifier,approval_status,"
            "observing_procedure_code,observing_procedure,vertical_datum,reading_type,measuring_agency")


def get_all(url, params, stem):
    page, n = 0, 0
    while url:
        out = RAW / f"{stem}_{page}.json"
        if out.exists():
            d = json.loads(out.read_text())
        else:
            for attempt in range(5):
                try:
                    r = requests.get(url, params=params, headers=UA, timeout=300)
                    if r.status_code == 429:
                        time.sleep(30 * (attempt + 1))
                        continue
                    r.raise_for_status()
                    d = r.json()
                    break
                except Exception as e:  # noqa: BLE001
                    if attempt == 4:
                        raise
                    time.sleep(10 * (attempt + 1))
            out.write_text(json.dumps(d))
        n += len(d["features"])
        nxt = [l["href"] for l in d.get("links", []) if l.get("rel") == "next"]
        url, params, page = (nxt[0] if nxt else None), None, page + 1
    return n


def fetch(code):
    fips = f"20{code:03d}"
    try:
        nfm = get_all(API + "field-measurements/items",
                      {"f": "json", "state_code": "20", "county_code": f"{code:03d}", "parameter_code": "72019",
                       "limit": 10000, "properties": FM_PROPS}, f"{fips}_fm")
        nml = get_all(API + "monitoring-locations/items",
                      {"f": "json", "state_code": "20", "county_code": f"{code:03d}", "site_type_code": "GW",
                       "limit": 10000}, f"{fips}_ml")
        return f"{fips} ok fm={nfm} ml={nml}"
    except Exception as e:  # noqa: BLE001
        return f"{fips} FAILED {e!r}"


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=3) as ex:
        for m in ex.map(fetch, COUNTIES):
            print(m, flush=True)
