"""storms module, step 2: what NASA Earthdata products exist for 2023-2026 over the basins, and what blocks them.

Uses the public NASA CMR search API (https://cmr.earthdata.nasa.gov/search, no login) to confirm that SMAP,
GPM IMERG daily (Final/Late), ECOSTRESS and GRACE-FO granules exist over the two basins for 2023-2026, then
tries to download one data URL per data host (no credentials) to record the exact auth/network failure.

Output: data/processed/earthdata_check.json
Re-run: python3 pipeline/p15_earthdata_check.py
"""
import datetime as dt
import json
import netrc
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))
from common import PROC, UA  # noqa: E402

CMR = "https://cmr.earthdata.nasa.gov/search"
BBOX = "-96.2,41.4,-93.5,44.3"  # both basins (Raccoon + Des Moines above Des Moines, incl. southern MN)
T0, T1 = "2023-01-01T00:00:00Z", dt.date.today().isoformat() + "T23:59:59Z"
PRODUCTS = [
    # short_name, version (None = any/latest), role in the model if it were reachable
    ("SPL3SMP_E", None, "SMAP L3 enhanced 9 km daily surface soil moisture: replaces POWER GWETTOP"),
    ("SPL4SMGP", None, "SMAP L4 3-hourly 9 km surface + ROOT-ZONE soil moisture: replaces POWER GWETROOT (p16)"),
    ("GPM_3IMERGDF", "07", "GPM IMERG V07 Final daily 0.1 deg: basin rainfall 2022+ (Final lags ~3.5 months)"),
    ("GPM_3IMERGDL", "07", "GPM IMERG V07 Late daily 0.1 deg: near-real-time basin rainfall for the outlook"),
    ("GPM_3IMERGHH", "07", "GPM IMERG V07 Final half-hourly: storm intensity (max30) 2022+"),
    ("ECO_L2T_LSTE", "002", "ECOSTRESS tiled 70 m land-surface temperature: field-scale ET/stress (not used)"),
    ("TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.3_V4", None,
     "GRACE/GRACE-FO JPL mascon monthly TWS: basin water-storage anomaly (slow groundwater driver)"),
    ("GRACEDADM_CLSM0125US_7D", None, "GRACE-DA weekly groundwater/root-zone drought indicators (CONUS 0.125 deg)"),
]
S = requests.Session()
S.headers.update(UA)


def cmr(path, **params):
    r = S.get(f"{CMR}/{path}", params=params, timeout=90)
    r.raise_for_status()
    return r


def collection(short, ver):
    p = dict(short_name=short, page_size=10)
    if ver:
        p["version"] = ver
    e = cmr("collections.json", **p).json()["feed"]["entry"]
    if not e:
        return None
    e = sorted(e, key=lambda x: x.get("version_id", ""))[-1]
    return dict(concept_id=e["id"], version=e.get("version_id"), provider=e.get("data_center"),
                title=e.get("title"), time_start=e.get("time_start"), time_end=e.get("time_end"))


def granules(cid, t0, t1, sort="start_date", n=1):
    r = cmr("granules.json", collection_concept_id=cid, bounding_box=BBOX, temporal=f"{t0},{t1}",
            page_size=n, sort_key=sort)
    return int(r.headers.get("CMR-Hits", 0)), r.json()["feed"]["entry"]


def data_urls(g):
    out = []
    for lk in g.get("links", []):
        h = lk.get("href", "")
        if lk.get("rel", "").endswith("/data#") and h.startswith("https") and not h.endswith((".xml", ".png")):
            out.append(h)
    return out


def try_url(url):
    """Unauthenticated GET; record each redirect hop and the final status or exception."""
    rec = dict(url=url, hops=[])
    try:
        u = url
        for _ in range(6):
            r = S.get(u, allow_redirects=False, timeout=60, stream=True)
            hop = dict(url=u, status=r.status_code, location=r.headers.get("Location"),
                       www_authenticate=r.headers.get("WWW-Authenticate"))
            rec["hops"].append(hop)
            r.close()
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                u = requests.compat.urljoin(u, r.headers["Location"])
                continue
            break
        last = rec["hops"][-1]
        rec["final_status"] = last["status"]
        rec["result"] = ("redirected to Earthdata Login (urs.earthdata.nasa.gov) - needs credentials"
                         if any("urs.earthdata.nasa.gov" in (h.get("location") or "") for h in rec["hops"])
                         else f"HTTP {last['status']}")
    except Exception as e:  # noqa: BLE001
        rec["error"] = f"{type(e).__name__}: {e}"[:600]
        rec["result"] = ("blocked by the container's network proxy (CONNECT 403)" if "403" in str(e) else
                         "network error")
    return rec


def creds_present():
    if os.environ.get("EARTHDATA_TOKEN"):
        return "EARTHDATA_TOKEN"
    try:
        if netrc.netrc().authenticators("urs.earthdata.nasa.gov"):
            return "~/.netrc"
    except (FileNotFoundError, netrc.NetrcParseError):
        pass
    return None


def main():
    out = dict(checked_at=dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               cmr=CMR, bbox_lonlat=BBOX, window=[T0, T1], credentials_found=creds_present(), products=[])
    tried_hosts = set()
    for short, ver, role in PRODUCTS:
        rec = dict(short_name=short, role=role)
        try:
            col = collection(short, ver)
            if not col:
                rec["error"] = "collection not found in CMR"
                out["products"].append(rec)
                continue
            rec["collection"] = col
            hits, first = granules(col["concept_id"], T0, T1, "start_date")
            _, last = granules(col["concept_id"], T0, T1, "-start_date")
            rec["granules_2023_on"] = hits
            rec["by_year"] = {str(y): granules(col["concept_id"], f"{y}-01-01T00:00:00Z",
                                               min(f"{y}-12-31T23:59:59Z", T1))[0] for y in range(2023, 2027)}
            rec["first_granule"] = first[0]["time_start"] if first else None
            rec["last_granule"] = last[0]["time_start"] if last else None
            if last:
                rec["sample_granule"] = last[0].get("producer_granule_id") or last[0].get("title")
                urls = data_urls(last[0])
                rec["sample_data_url"] = urls[0] if urls else None
                host = urls[0].split("/")[2] if urls else None
                if host and host not in tried_hosts:
                    tried_hosts.add(host)
                    rec["download_attempt"] = try_url(urls[0])
        except Exception as e:  # noqa: BLE001
            rec["error"] = f"{type(e).__name__}: {e}"[:400]
        out["products"].append(rec)
        print(f"{short:45s} v{(rec.get('collection') or {}).get('version')}: {rec.get('granules_2023_on')} granules "
              f"{rec.get('by_year')} last={rec.get('last_granule')}"
              + (f"\n   download -> {rec['download_attempt'].get('result')} "
                 f"{rec['download_attempt'].get('error', '')[:160]}" if "download_attempt" in rec else ""),
              flush=True)
    # Earthdata Login endpoint itself
    out["urs_probe"] = try_url("https://urs.earthdata.nasa.gov/")
    print("urs.earthdata.nasa.gov ->", out["urs_probe"].get("result"), out["urs_probe"].get("error", "")[:160])
    out["summary"] = dict(
        all_found_with_granules=all(p.get("granules_2023_on", 0) > 0 for p in out["products"]),
        blocked=[dict(host=p["sample_data_url"].split("/")[2], product=p["short_name"],
                      result=p["download_attempt"]["result"], error=p["download_attempt"].get("error"),
                      hops=[(h["status"], (h.get("location") or "")[:120]) for h in p["download_attempt"]["hops"]])
                 for p in out["products"] if "download_attempt" in p],
        unblock=("Free NASA Earthdata Login account (https://urs.earthdata.nasa.gov/users/new), approve the "
                 "'NASA GESDISC DATA ARCHIVE' and NSIDC applications, put credentials in ~/.netrc "
                 "(machine urs.earthdata.nasa.gov login <u> password <p>) or export EARTHDATA_TOKEN; and the "
                 "data hosts listed above must be added to the container's network allow-list."),
    )
    (PROC / "earthdata_check.json").write_text(json.dumps(out, indent=1))
    print("wrote", PROC / "earthdata_check.json")


if __name__ == "__main__":
    main()
