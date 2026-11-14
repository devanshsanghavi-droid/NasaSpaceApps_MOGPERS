"""econ: stream USDA NASS QuickStats bulk files and keep only the Kansas rows this app needs.

The bulk files (qs.crops_YYYYMMDD.txt.gz ~1.1 GB gz, qs.census2022.txt.gz ~0.3 GB gz) are streamed and filtered
line by line; the full files are never written to disk. Filtered rows are cached as TSV under data/raw/nass/.

Run: python3 pipeline/econ_nass_fetch.py [crops|census2022|all] [--refresh]
Source listing: https://www.nass.usda.gov/datasets (QuickStats API at quickstats.nass.usda.gov is blocked here).
"""
import gzip
import io
import re
import sys
import time
from pathlib import Path

import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "nass"
RAW.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "water-clock-hackathon"}
LISTING = "https://www.nass.usda.gov/datasets"
BASE = "https://www.nass.usda.gov/sites/default/files/datasets/"

# Region counties (Kansas county ANSI codes), from CONTRACTS.md
REGION = {
    "071": "GMD1", "203": "GMD1", "171": "GMD1", "101": "GMD1",
    "075": "GMD3", "093": "GMD3", "055": "GMD3", "069": "GMD3", "057": "GMD3", "187": "GMD3", "067": "GMD3",
    "081": "GMD3", "129": "GMD3", "189": "GMD3", "175": "GMD3", "119": "GMD3",
    "023": "GMD4", "153": "GMD4", "039": "GMD4", "181": "GMD4", "193": "GMD4", "179": "GMD4", "199": "GMD4",
    "109": "GMD4", "063": "GMD4", "065": "GMD4",
}
CROPS = {"CORN", "SORGHUM", "WHEAT", "SOYBEANS", "COTTON"}
CROP_STATS = {"YIELD", "AREA HARVESTED", "AREA PLANTED", "PRODUCTION", "PRICE RECEIVED"}


def find_url(kind):
    html = requests.get(LISTING, headers=UA, timeout=60).text
    pat = r'href="(/sites/default/files/datasets/qs\.%s(?:_\d{8})?\.txt\.gz)"' % re.escape(kind)
    m = re.findall(pat, html)
    if not m:
        raise RuntimeError(f"qs.{kind} link not found on {LISTING}")
    return "https://www.nass.usda.gov" + sorted(m)[-1]


def keep_crops(f, ix):
    if f[ix["STATE_ALPHA"]] != "KS" or f[ix["COMMODITY_DESC"]] not in CROPS:
        return False
    if f[ix["STATISTICCAT_DESC"]] not in CROP_STATS:
        return False
    agg = f[ix["AGG_LEVEL_DESC"]]
    if agg == "STATE":
        return True
    if agg == "AGRICULTURAL DISTRICT":
        return True
    if agg == "COUNTY":
        # keep region counties plus "OTHER (COMBINED) COUNTIES" rows (blank COUNTY_ANSI) of the western districts
        ca = f[ix["COUNTY_ANSI"]].strip()
        return ca in REGION or (ca == "" and f[ix["ASD_CODE"]].strip() in ("10", "40", "70"))
    return False


def keep_census(f, ix):
    if f[ix["STATE_ALPHA"]] != "KS":
        return False
    agg = f[ix["AGG_LEVEL_DESC"]]
    if agg == "STATE":
        return True
    if agg == "COUNTY":
        return f[ix["COUNTY_ANSI"]].strip() in REGION
    return False


def stream(url, keep, prefilter, out_path):
    print("streaming", url, flush=True)
    t0 = time.time()
    with requests.get(url, headers=UA, stream=True, timeout=180) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        gz = gzip.GzipFile(fileobj=r.raw)
        txt = io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")
        header_line = txt.readline()
        header = header_line.rstrip("\r\n").split("\t")
        ix = {h: i for i, h in enumerate(header)}
        n = kept = 0
        tmp = out_path.with_suffix(".part")
        with open(tmp, "w", encoding="utf-8") as fo:
            fo.write("\t".join(header + ["_SOURCE_URL"]) + "\n")
            for line in txt:
                n += 1
                if n % 5_000_000 == 0:
                    print(f"  {n:,} lines, {kept:,} kept, {time.time()-t0:.0f}s", flush=True)
                if prefilter not in line:
                    continue
                f = line.rstrip("\r\n").split("\t")
                if len(f) != len(header) or not keep(f, ix):
                    continue
                fo.write("\t".join(f + [url]) + "\n")
                kept += 1
        tmp.replace(out_path)
    print(f"done {url}: {n:,} lines, {kept:,} kept, {time.time()-t0:.0f}s -> {out_path}", flush=True)


def main():
    what = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "all"
    refresh = "--refresh" in sys.argv
    jobs = []
    if what in ("crops", "all"):
        jobs.append(("crops", keep_crops, RAW / "ks_crops_rows.tsv"))
    if what in ("census2022", "all"):
        jobs.append(("census2022", keep_census, RAW / "ks_census2022_rows.tsv"))
    for kind, keep, out in jobs:
        if out.exists() and not refresh:
            print("cached", out)
            continue
        stream(find_url(kind), keep, "\tKS\t", out)


if __name__ == "__main__":
    main()
