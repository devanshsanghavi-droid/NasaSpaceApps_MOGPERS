"""Fetch KGS WIZARD well sites + water levels for the Water Clock region counties.

Flow (verified 2026-11-14):
  1. POST multipart form to https://geohydro.kgs.ku.edu/geohydro/wizard/wizardviewer.cfm
     (fields from wizard/index.html: f_c=<county code>, f_only=Y, ...). Server stores the
     selection in a ColdFusion session and 302-redirects to wizardwelllisting.cfm.
  2. GET wizarddownload.cfm in the same session -> page links two CSVs
     (sites<stamp>.csv, wlevel<stamp>.csv) on https://maps.kgs.ku.edu/gh/geohydro/downloads/.
     maps.kgs.ku.edu is refused by the session proxy, but the same files are served at
     https://geohydro.kgs.ku.edu/geohydro/downloads/<file> so we rewrite the host.
Raw CSVs cached in data/raw/kgs/<county_fips>_{sites,wlevel}.csv.
"""
import re
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "kgs"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "water-clock-hackathon"}
BASE = "https://geohydro.kgs.ku.edu/geohydro/wizard/"
DL_HOST = "https://geohydro.kgs.ku.edu/geohydro/downloads/"

# Kansas county code (3-digit FIPS) -> (name, GMD) from CONTRACTS.md
COUNTIES = {
    71: ("Greeley", 1), 203: ("Wichita", 1), 171: ("Scott", 1), 101: ("Lane", 1),
    75: ("Hamilton", 3), 93: ("Kearny", 3), 55: ("Finney", 3), 69: ("Gray", 3), 57: ("Ford", 3),
    187: ("Stanton", 3), 67: ("Grant", 3), 81: ("Haskell", 3), 129: ("Morton", 3), 189: ("Stevens", 3),
    175: ("Seward", 3), 119: ("Meade", 3),
    23: ("Cheyenne", 4), 153: ("Rawlins", 4), 39: ("Decatur", 4), 181: ("Sherman", 4), 193: ("Thomas", 4),
    179: ("Sheridan", 4), 199: ("Wallace", 4), 109: ("Logan", 4), 63: ("Gove", 4), 65: ("Graham", 4),
}


def fetch_county(code: int, force: bool = False) -> str:
    fips = f"20{code:03d}"
    out_s, out_w = RAW / f"{fips}_sites.csv", RAW / f"{fips}_wlevel.csv"
    if out_s.exists() and out_w.exists() and not force:
        return f"{fips} cached"
    for attempt in range(4):
        try:
            s = requests.Session()
            s.headers.update(UA)
            form = {"f_t": "0", "f_r": "0", "ew": "W", "f_s": "0", "f_c": str(code), "f_gmd": "0",
                    "f_st": "20", "f_only": "Y", "f_dstart": "", "f_dend": "", "f_usgs": "", "f_kgsid": "",
                    "f_nlat": "", "f_slat": "", "f_wlong": "", "f_elong": ""}
            files = {k: (None, v) for k, v in form.items()}
            r = s.post(BASE + "wizardviewer.cfm", files=files, timeout=300)
            r.raise_for_status()
            r = s.get(BASE + "wizarddownload.cfm", timeout=600)
            r.raise_for_status()
            links = re.findall(r'href="[^"]*/downloads/((?:sites|wlevel)\d+\.csv)"', r.text)
            sites = [l for l in links if l.startswith("sites")]
            wl = [l for l in links if l.startswith("wlevel")]
            if not sites or not wl:
                raise RuntimeError(f"no download links in wizarddownload.cfm for {fips}")
            for fn, out in ((sites[0], out_s), (wl[0], out_w)):
                rr = s.get(DL_HOST + fn, timeout=600)
                rr.raise_for_status()
                tmp = out.with_suffix(".tmp")
                tmp.write_bytes(rr.content)
                tmp.rename(out)
            return f"{fips} ok sites={sum(1 for _ in open(out_s)) - 1} wl={sum(1 for _ in open(out_w)) - 1}"
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(5 * (attempt + 1))
    return f"{fips} FAILED {err!r}"


if __name__ == "__main__":
    force = "--force" in sys.argv
    with ThreadPoolExecutor(max_workers=3) as ex:
        for msg in ex.map(lambda c: fetch_county(c, force), COUNTIES):
            print(msg, flush=True)
