"""Build the 30 m USDA Cropland Data Layer mosaic for the region, one GeoTIFF per year:
data/raw/cdl/cdl_<year>_region.tif (EPSG:5070, native CDL 30 m grid, no resampling).

- 2008-2021: Microsoft Planetary Computer STAC collection `usda-cdl` (usda_cdl:type = cropland), 90 km COG tiles on
  landcoverdata.blob.core.windows.net, URLs signed with planetary_computer.
- 2022-2024 (not on Planetary Computer): USDA NASS national 30 m CDL zips
  https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/<year>_30m_cdls.zip
  Only the byte range of the .tif member is downloaded (parallel HTTP range requests), inflated locally, the region window
  is clipped and the national file deleted.

Usage: python3 pipeline/nasa_cdl_fetch.py [years...]
"""
import os
import struct
import sys
import time
import zlib
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import rasterio
import requests
from rasterio.windows import from_bounds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nasa_cdl_common import CDL_RAW, CDL_YEARS, GDAL_ENV, STAC, cdl_path, region_grid, retry  # noqa: E402

NASS_URL = "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/{y}_30m_cdls.zip"
UA = {"User-Agent": "water-clock-hackathon"}


def write_tif(path, arr, tr, desc):
    prof = dict(driver="GTiff", height=arr.shape[0], width=arr.shape[1], count=1, dtype="uint8", crs="EPSG:5070",
                transform=tr, compress="deflate", tiled=True, nodata=0)
    tmp = str(path) + ".tmp"
    with rasterio.open(tmp, "w", **prof) as dst:
        dst.write(arr, 1)
        dst.update_tags(source=desc)
    os.replace(tmp, path)


def pc_items():
    import planetary_computer
    import pystac_client
    c = pystac_client.Client.open(STAC, modifier=planetary_computer.sign_inplace)
    s = c.search(collections=["usda-cdl"], bbox=[-102.1, 36.95, -99.5, 40.05], query={"usda_cdl:type": {"eq": "cropland"}})
    out = {}
    for it in s.items():
        out.setdefault(int(it.properties["start_datetime"][:4]), []).append(it)
    return out


def mosaic_pc(year, items):
    import planetary_computer
    bb, tr, W, H = region_grid()
    mos = np.zeros((H, W), np.uint8)
    used = []
    for it in items:
        href = it.assets["cropland"].href.split("?")[0]

        def read():
            with rasterio.Env(**GDAL_ENV), rasterio.open(planetary_computer.sign(href)) as src:
                assert src.crs.to_epsg() == 5070
                b = src.bounds
                if b.right <= bb[0] or b.left >= bb[2] or b.top <= bb[1] or b.bottom >= bb[3]:
                    return None
                win = from_bounds(*bb, transform=src.transform).round_offsets().round_lengths()
                return src.read(1, window=win, boundless=True, fill_value=0)
        arr = retry(read)
        if arr is None:
            continue
        assert arr.shape == (H, W), arr.shape
        m = (mos == 0) & (arr != 0)
        mos[m] = arr[m]
        used.append(it.id)
    write_tif(cdl_path(year), mos, tr, "planetary-computer usda-cdl cropland: " + ",".join(sorted(used)))
    return f"{len(used)} tiles, nodata frac={np.mean(mos == 0):.4f}"


def fetch_range(url, path, start, end):
    def go():
        r = requests.get(url, headers={**UA, "Range": f"bytes={start}-{end}"}, timeout=180)
        r.raise_for_status()
        if len(r.content) != end - start + 1:
            raise IOError(f"short read {len(r.content)}")
        with open(path, "r+b") as f:
            f.seek(start)
            f.write(r.content)
    retry(go, tries=8)


def nass_year(year):
    """Download only the .tif member of the national zip, inflate it, clip the region window."""
    import fsspec
    import zipfile
    url = NASS_URL.format(y=year)
    tmpd = CDL_RAW / "nass_tmp"
    tmpd.mkdir(parents=True, exist_ok=True)
    with fsspec.open(url, headers=UA, block_size=2**20, client_kwargs={"trust_env": True}).open() as f:
        z = zipfile.ZipFile(f)
        info = [i for i in z.infolist() if i.filename.endswith("_30m_cdls.tif")][0]
        f.seek(info.header_offset)
        hdr = f.read(30)
        sig, _, _, method, _, _, _, csize, usize, nlen, xlen = struct.unpack("<IHHHHHIIIHH", hdr)
        assert sig == 0x04034B50 and method == 8, (sig, method)
    start = info.header_offset + 30 + nlen + xlen
    end = start + info.compress_size - 1
    part = tmpd / f"{year}.deflate"
    done = tmpd / f"{year}.deflate.done"
    if not done.exists():
        with open(part, "wb") as fh:
            fh.truncate(end + 1)           # sparse file; bytes before `start` unused
        chunk = 32 * 2**20
        ranges = [(s, min(s + chunk, end + 1) - 1) for s in range(start, end + 1, chunk)]
        t0 = time.time()
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda r: fetch_range(url, part, *r), ranges))
        print(f"  {year}: downloaded {info.compress_size/1e9:.2f} GB in {time.time()-t0:.0f}s", flush=True)
        done.touch()
    tif = tmpd / f"{year}_30m_cdls.tif"
    d = zlib.decompressobj(-15)
    crc = 0
    with open(part, "rb") as fi, open(tif, "wb") as fo:
        fi.seek(start)
        left = info.compress_size
        while left > 0:
            buf = fi.read(min(16 * 2**20, left))
            left -= len(buf)
            out = d.decompress(buf)
            crc = zlib.crc32(out, crc)
            fo.write(out)
        out = d.flush()
        crc = zlib.crc32(out, crc)
        fo.write(out)
    assert crc == info.CRC, "CRC mismatch"
    bb, tr, W, H = region_grid()
    with rasterio.open(tif) as src:
        assert src.crs.to_epsg() == 5070 or "Albers" in src.crs.to_wkt(), src.crs
        win = from_bounds(*bb, transform=src.transform)
        assert abs(win.col_off - round(win.col_off)) < 1e-6 and abs(win.row_off - round(win.row_off)) < 1e-6, win
        win = win.round_offsets().round_lengths()
        arr = src.read(1, window=win, boundless=True, fill_value=0)
    assert arr.shape == (H, W)
    write_tif(cdl_path(year), arr, tr, url)
    for p in (tif, part, done):
        p.unlink()
    return f"NASS zip, nodata frac={np.mean(arr == 0):.4f}"


def main():
    CDL_RAW.mkdir(parents=True, exist_ok=True)
    years = [int(a) for a in sys.argv[1:] if a.isdigit()] or CDL_YEARS
    todo = [y for y in years if not cdl_path(y).exists()]
    print("todo:", todo, flush=True)
    pc_years = [y for y in todo if y <= 2021]
    nass_years = [y for y in todo if y >= 2022]
    if pc_years:
        by = pc_items()
        with ThreadPoolExecutor(3) as ex:
            for y, msg in zip(pc_years, ex.map(lambda y: mosaic_pc(y, by[y]), pc_years)):
                print(y, msg, flush=True)
    for y in nass_years:
        print(y, nass_year(y), flush=True)


if __name__ == "__main__":
    main()
