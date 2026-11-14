"""Fetch Kansas WIMAS water-right / point-of-diversion / reported water-use tables for the Water Clock counties.

WIMAS = Water Information Management and Analysis System (KGS + Kansas Dept. of Agriculture, Division of Water Resources).
Flow (verified 2026-11-14, ColdFusion app, needs a cookie session):
  1. GET  https://geohydro.kgs.ku.edu/geohydro/wimas/index.cfm             (sets CFID/CFTOKEN/JSESSIONID cookies)
  2. POST query_setup.cfm  wimas_accept=Accept  (Referer index.cfm)        (disclaimer acceptance -> query form)
  3. POST query_setup.cfm  multipart: county='XX', umwf='IRR' & umwf='MUN', a_v=on (appropriated/vested primary rights),
     source=n (no source filter), user_email=<required field>               -> 302 to query_results.cfm (selection kept in session)
  4. GET  query_results.cfm (materialises the selection)
  5. GET  download.cfm?type=main&active=no   -> link to wimas_<stamp>.txt  (water right x point of diversion, lon/lat, PLSS, gmd)
     GET  download.cfm?type=qty               -> link to qty_<stamp>.txt    (authorized quantity per water right x PD, AF)
     GET  wuse_trends.cfm (POST wuse_start/wuse_end/T_Submit) then download.cfm?type=wuse&syear=..&eyear=..
                                              -> link to wuse_<stamp>.txt   (annual water-use report per right x PD x year:
                                                 af_used, acres_irr, crop_code, type_system, meter info, ...)
  The download links point to https://maps.kgs.ku.edu/gh/geohydro/downloads/<file>; maps.kgs.ku.edu is refused by the
  session proxy, but the identical file is served at https://geohydro.kgs.ku.edu/geohydro/downloads/<file>.
The query form requires an e-mail address; we send a generic non-personal placeholder (no personal data in requests).
Raw text files are cached in data/raw/wimas/<fips>_{main,qty,wuse}.txt.
Usage: python3 pipeline/pumping_fetch.py [--force] [--workers 2]
"""
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "wimas"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "water-clock-hackathon"}
BASE = "https://geohydro.kgs.ku.edu/geohydro/wimas/"
DL_HOST = "https://geohydro.kgs.ku.edu/geohydro/downloads/"
GENERIC_EMAIL = "water-clock-hackathon@example.com"  # required form field; deliberately non-personal
Y0, Y1 = 1990, 2025

# 3-digit Kansas county FIPS -> (name, WIMAS county code, contract GMD)
COUNTIES = {
    71: ("Greeley", "GL", 1), 203: ("Wichita", "WH", 1), 171: ("Scott", "SC", 1), 101: ("Lane", "LE", 1),
    75: ("Hamilton", "HM", 3), 93: ("Kearny", "KE", 3), 55: ("Finney", "FI", 3), 69: ("Gray", "GY", 3),
    57: ("Ford", "FO", 3), 187: ("Stanton", "ST", 3), 67: ("Grant", "GT", 3), 81: ("Haskell", "HS", 3),
    129: ("Morton", "MT", 3), 189: ("Stevens", "SV", 3), 175: ("Seward", "SW", 3), 119: ("Meade", "ME", 3),
    23: ("Cheyenne", "CN", 4), 153: ("Rawlins", "RA", 4), 39: ("Decatur", "DC", 4), 181: ("Sherman", "SH", 4),
    193: ("Thomas", "TH", 4), 179: ("Sheridan", "SD", 4), 199: ("Wallace", "WA", 4), 109: ("Logan", "LG", 4),
    63: ("Gove", "GO", 4), 65: ("Graham", "GH", 4),
}


def _get(s, url, **kw):
    for attempt in range(4):
        try:
            r = s.get(url, headers=UA, timeout=kw.pop("timeout", 900), **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 3:
                raise
            print(f"  retry GET {url}: {e}", flush=True)
            time.sleep(5 * (attempt + 1))


def _download_link(html: str) -> str:
    m = re.search(r'https?://maps\.kgs\.ku\.edu/gh/geohydro/downloads/([A-Za-z0-9_]+\.txt)', html)
    if not m:
        raise RuntimeError("no download link in page: " + re.sub(r"<[^>]+>", " ", html)[:500])
    return DL_HOST + m.group(1)


def new_session(code: str, twp: str = "0") -> requests.Session:
    s = requests.Session()
    _get(s, BASE + "index.cfm")
    r = s.post(BASE + "query_setup.cfm", data={"wimas_accept": "Accept"},
               headers={**UA, "Referer": BASE + "index.cfm"}, timeout=120)
    r.raise_for_status()
    if "county" not in r.text:
        raise RuntimeError("disclaimer acceptance did not return the query form")
    fields = [("twp", twp), ("rng", "0"), ("rng_dir", "0"), ("sect", "0"), ("f_nlat", ""), ("f_wlong", ""),
              ("f_elong", ""), ("f_slat", ""), ("county", f"'{code}'"), ("rt", "0"), ("vc", "0"), ("wn", ""),
              ("wq", ""), ("umwf", "'MUN'"), ("umwf", "'IRR'"), ("a_v", "on"), ("source", "n"),
              ("user_email", GENERIC_EMAIL), ("Select_wells_button", "Select Water Rights")]
    r = s.post(BASE + "query_setup.cfm", files=[(k, (None, v)) for k, v in fields],
               headers={**UA, "Referer": BASE + "query_setup.cfm"}, timeout=300)
    r.raise_for_status()
    if "unique water rights" not in r.text:
        r = _get(s, BASE + "query_results.cfm")
    m = re.search(r"There are (\d+) unique water rights and (\d+) unique points of diversion", r.text)
    if not m:
        raise RuntimeError("query did not return a result set")
    print(f"  {code}: {m.group(1)} water rights, {m.group(2)} PDs selected", flush=True)
    s.n_pdiv = int(m.group(2))
    return s


def fetch_wuse(s, y0: int, y1: int) -> bytes:
    """Run the (slow, server-side) water-use trend query for years y0..y1 and return the raw text file."""
    r = s.post(BASE + "wuse_trends.cfm", data={"wuse_start": str(y0), "wuse_end": str(y1),
                                               "T_Submit": "Submit/Download Trend Request"},
               headers={**UA, "Referer": BASE + "wuse_trends.cfm"}, timeout=1800)
    r.raise_for_status()
    link = _download_link(_get(s, BASE + f"download.cfm?type=wuse&syear={y0}&eyear={y1}", timeout=3600).text)
    return _get(s, link).content


def fetch_wuse_by_township(code: str, year: int):
    """Fallback for a county-year whose WIMAS query errors server-side: query each PLSS township (1-35 S) separately.
    Returns the merged raw text, or None if any township with rights still fails."""
    parts = []
    for twp in range(1, 36):
        try:
            s = new_session(code, str(twp))
        except (RuntimeError, requests.HTTPError):
            continue  # no rights in this township for this county (WIMAS answers 500 "WIMAS_WHERE is undefined")
        try:
            txt = fetch_wuse(s, year, year)
        except requests.HTTPError as e:
            print(f"  {code} {year} twp {twp}S: {e}", flush=True)
            return None
        lines = txt.splitlines(keepends=True)
        parts.append(lines if not parts else lines[1:])
    return b"".join(l for p in parts for l in p) if parts else None


def fetch_county(c3: int, force: bool = False) -> dict:
    name, code, gmd = COUNTIES[c3]
    fips = f"20{c3:03d}"
    out = {k: RAW / f"{fips}_{k}.txt" for k in ("main", "qty", "wuse")}
    if not force and all(p.exists() and p.stat().st_size > 200 for p in out.values()):
        return {"fips": fips, "status": "cached"}
    t0 = time.time()
    s = new_session(code)
    # main (water right x PD)
    link = _download_link(_get(s, BASE + "download.cfm?type=main&active=no").text)
    out["main"].write_bytes(_get(s, link).content)
    # authorized quantities
    _get(s, BASE + "qty_sum.cfm")
    link = _download_link(_get(s, BASE + "download.cfm?type=qty").text)
    out["qty"].write_bytes(_get(s, link).content)
    # reported water use (slow server-side query). Large counties are split into year windows because a single
    # 1990-2025 request for e.g. Finney (3,243 PDs) outlives the proxy connection ("Remote end closed connection").
    step = 36 if s.n_pdiv <= 800 else max(3, int(36 * 700 / s.n_pdiv))
    chunks, missing = [], []

    def run(y0, y1):
        try:
            txt = fetch_wuse(s, y0, y1)
        except requests.HTTPError as e:
            # e.g. Sherman 1990-2014: "500 Server Error: Error Executing Database Query" -> split the window
            if y1 > y0:
                print(f"  {fips} wuse {y0}-{y1}: {e}; splitting", flush=True)
                mid = (y0 + y1) // 2
                run(y0, mid)
                run(mid + 1, y1)
                return
            # a single year that still fails is skipped and recorded (see notes/pumping.md); try PLSS-township subsets
            sub = fetch_wuse_by_township(code, y0)
            if sub is None:
                missing.append(f"{y0}\t{e}")
                print(f"  {fips} wuse {y0}: FAILED even as single year -> recorded as missing", flush=True)
                return
            txt = sub
        lines = txt.splitlines(keepends=True)
        chunks.append(lines if not chunks else lines[1:])  # keep header once
        print(f"  {fips} wuse {y0}-{y1}: {len(lines)-1} rows", flush=True)

    for y0 in range(Y0, Y1 + 1, step):
        run(y0, min(Y1, y0 + step - 1))
    out["wuse"].write_bytes(b"".join(l for c in chunks for l in c))
    miss_file = RAW / f"{fips}_wuse_missing.txt"
    if missing:
        miss_file.write_text("\n".join(missing) + "\n")
    elif miss_file.exists():
        miss_file.unlink()
    sizes = {k: p.stat().st_size for k, p in out.items()}
    print(f"  {fips} {name}: done in {time.time()-t0:.0f}s {sizes}", flush=True)
    return {"fips": fips, "status": "ok", **sizes}


def main():
    force = "--force" in sys.argv
    workers = 2
    if "--workers" in sys.argv:
        workers = min(4, int(sys.argv[sys.argv.index("--workers") + 1]))
    errors = {}

    def job(c3):
        try:
            return fetch_county(c3, force)
        except Exception as e:  # record the exact error, keep going
            errors[c3] = repr(e)
            print(f"  ERROR {c3}: {e!r}", flush=True)
            return None

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(job, sorted(COUNTIES)))
    (RAW / "fetch_errors.txt").write_text("\n".join(f"20{k:03d}\t{v}" for k, v in errors.items()))
    print("errors:", errors or "none")


if __name__ == "__main__":
    main()
