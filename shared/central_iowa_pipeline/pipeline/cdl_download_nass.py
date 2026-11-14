"""Download national 30 m CDL zips from USDA NASS for years missing on Planetary Computer
(2022-2024), using parallel HTTP range requests, then clip the tile window to
data/raw/cdl/cdl_<year>_tile.tif (EPSG:5070). Big zip/tif are deleted after clipping
unless --keep is passed.

Usage: .venv/bin/python pipeline/cdl_download_nass.py [years...] [--keep]
"""
import os, sys, zipfile, shutil, time
from concurrent.futures import ThreadPoolExecutor
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(ROOT, "data", "raw", "cdl")
ZDIR = os.path.join(RAW, "nass_zip")
UA = {"User-Agent": "counterfield-hackathon"}
URL = "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/{y}_30m_cdls.zip"
CHUNK = 32 * 2**20

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import tile_bbox_5070, clip_to_tile  # noqa: E402


def fetch_range(url, path, start, end, tries=6):
    for k in range(tries):
        try:
            r = requests.get(url, headers={**UA, "Range": f"bytes={start}-{end}"}, timeout=120)
            r.raise_for_status()
            data = r.content
            if len(data) != end - start + 1:
                raise IOError(f"short read {len(data)} vs {end-start+1}")
            with open(path, "r+b") as f:
                f.seek(start)
                f.write(data)
            return
        except Exception as e:  # retry
            print(f"  retry {k} {start}: {e}", flush=True)
            time.sleep(3 * (k + 1))
    raise RuntimeError(f"range {start}-{end} failed")


def download(year):
    url = URL.format(y=year)
    out = os.path.join(ZDIR, f"{year}_30m_cdls.zip")
    done = out + ".done"
    if os.path.exists(done):
        return out
    size = int(requests.head(url, headers=UA, timeout=60).headers["content-length"])
    with open(out, "wb") as f:
        f.truncate(size)
    ranges = [(s, min(s + CHUNK, size) - 1) for s in range(0, size, CHUNK)]
    t0 = time.time()
    with ThreadPoolExecutor(10) as ex:
        list(ex.map(lambda r: fetch_range(url, out, *r), ranges))
    print(f"{year}: downloaded {size/1e9:.2f} GB in {time.time()-t0:.0f}s", flush=True)
    open(done, "w").close()
    return out


def main():
    keep = "--keep" in sys.argv
    years = [int(a) for a in sys.argv[1:] if a.isdigit()] or [2022, 2023, 2024]
    os.makedirs(ZDIR, exist_ok=True)
    for y in years:
        tile = os.path.join(RAW, f"cdl_{y}_tile.tif")
        if os.path.exists(tile):
            print(f"{y}: cached {tile}")
            continue
        z = download(y)
        exdir = os.path.join(ZDIR, f"x{y}")
        os.makedirs(exdir, exist_ok=True)
        with zipfile.ZipFile(z) as zf:
            for m in zf.namelist():
                if m.endswith(".tif") and not m.endswith(".ovr"):
                    tifp = zf.extract(m, exdir)
        clip_to_tile(tifp, tile, src_desc=URL.format(y=y))
        print(f"{y}: clipped -> {tile}", flush=True)
        if not keep:
            shutil.rmtree(exdir, ignore_errors=True)
            os.remove(z)
            os.remove(z + ".done")


if __name__ == "__main__":
    main()
