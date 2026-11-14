"""CDL years missing on Planetary Computer (2022-2024): official USDA NASS national 30 m release.

Only the .tif member of the national zip is fetched (HTTP range requests on the zip; the .ovr member is skipped),
inflated to a local GeoTIFF, sampled on the fixed lattice (data/raw/cdl/lattice_<year>.npy, uint8 NY x NX),
and Plymouth County is clipped at full 30 m (data/raw/cdl/focus/cdl_<year>_19149.tif). The big files are then
deleted (pass --keep to keep them).

Usage: python pipeline/cdl_nass_fetch.py [years...] [--keep] [--threads N]
"""
import io, os, sys, time, zlib, struct, zipfile
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import requests
import rasterio
from rasterio.windows import Window, from_bounds

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import (RAW, UA, NASS_YEARS, NX, NY, lattice_index_for_raster, lattice_path,  # noqa: E402
                        focus_bbox_5070, focus_path, write_focus_tif)

URL = "https://www.nass.usda.gov/sites/default/files/Research_and_Science/Cropland/Release/datasets/{y}_30m_cdls.zip"
ZDIR = os.path.join(RAW, "nass_tmp")
CHUNK = 32 * 2**20


class HTTPFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (used only to read the zip central directory)."""
    def __init__(self, url):
        self.url, self.pos = url, 0
        self.size = int(requests.head(url, headers=UA, timeout=60).headers["content-length"])

    def seekable(self): return True
    def readable(self): return True
    def tell(self): return self.pos

    def seek(self, o, w=0):
        self.pos = o if w == 0 else (self.pos + o if w == 1 else self.size + o)
        return self.pos

    def read(self, n=-1):
        if n < 0:
            n = self.size - self.pos
        if n == 0:
            return b""
        r = requests.get(self.url, headers={**UA, "Range": f"bytes={self.pos}-{self.pos + n - 1}"}, timeout=120)
        r.raise_for_status()
        self.pos += len(r.content)
        return r.content


def fetch_tif(year, threads):
    """Download the deflated .tif member bytes and inflate them to ZDIR/<year>_30m_cdls.tif."""
    url = URL.format(y=year)
    tif = os.path.join(ZDIR, f"{year}_30m_cdls.tif")
    if os.path.exists(tif + ".done"):
        return tif
    zf = zipfile.ZipFile(HTTPFile(url))
    info = [i for i in zf.infolist() if i.filename.endswith(".tif")][0]
    assert info.compress_type in (0, 8), info.compress_type
    # local header: 30 bytes + name + extra
    hdr = requests.get(url, headers={**UA, "Range": f"bytes={info.header_offset}-{info.header_offset + 29}"},
                       timeout=60).content
    sig, = struct.unpack("<I", hdr[:4]); assert sig == 0x04034B50
    nlen, xlen = struct.unpack("<HH", hdr[26:30])
    start = info.header_offset + 30 + nlen + xlen
    size = info.compress_size
    comp = os.path.join(ZDIR, f"{year}_tif.deflate")
    if not os.path.exists(comp + ".done"):
        with open(comp, "wb") as f:
            f.truncate(size)
        ranges = [(s, min(s + CHUNK, size) - 1) for s in range(0, size, CHUNK)]
        t0 = time.time()
        with ThreadPoolExecutor(threads) as ex:
            list(ex.map(lambda r: _fetch_rel(url, comp, start, r), ranges))
        print(f"{year}: downloaded {size / 1e9:.2f} GB in {time.time() - t0:.0f}s", flush=True)
        open(comp + ".done", "w").close()
    t0 = time.time()
    crc = 0
    with open(comp, "rb") as fi, open(tif, "wb") as fo:
        d = zlib.decompressobj(-15) if info.compress_type == 8 else None
        while True:
            buf = fi.read(16 * 2**20)
            if not buf:
                break
            out = d.decompress(buf) if d else buf
            crc = zlib.crc32(out, crc)
            fo.write(out)
        if d:
            out = d.flush(); crc = zlib.crc32(out, crc); fo.write(out)
    assert os.path.getsize(tif) == info.file_size, (os.path.getsize(tif), info.file_size)
    assert crc == info.CRC, "CRC mismatch"
    print(f"{year}: inflated {info.file_size / 1e9:.2f} GB in {time.time() - t0:.0f}s (CRC ok)", flush=True)
    open(tif + ".done", "w").close()
    os.remove(comp); os.remove(comp + ".done")
    return tif


def _fetch_rel(url, path, base, r):
    """Fetch absolute bytes base+r[0]..base+r[1] of the zip and write them at offset r[0] of path."""
    s, e = r
    for k in range(8):
        try:
            resp = requests.get(url, headers={**UA, "Range": f"bytes={base + s}-{base + e}"}, timeout=180)
            resp.raise_for_status()
            data = resp.content
            if len(data) != e - s + 1:
                raise IOError(f"short read {len(data)} vs {e - s + 1}")
            with open(path, "r+b") as f:
                f.seek(s)
                f.write(data)
            return
        except Exception as ex:
            print(f"  retry {k} @{s}: {ex}", flush=True)
            time.sleep(4 * (k + 1))
    raise RuntimeError(f"range {s}-{e} failed")


def sample_lattice(tif, year):
    out = np.zeros((NY, NX), np.uint8)
    with rasterio.open(tif) as src:
        assert src.crs.to_epsg() == 5070 or "Albers" in src.crs.to_wkt(), src.crs
        lr, lc, pr, pc = lattice_index_for_raster(src.transform, src.height, src.width)
        c0, c1 = int(pc.min()), int(pc.max()) + 1
        step = 1024
        r_lo = int(pr.min())
        for r0 in range(r_lo - r_lo % step, int(pr.max()) + 1, step):
            sel = (pr >= r0) & (pr < r0 + step)
            if not sel.any():
                continue
            arr = src.read(1, window=Window(c0, r0, c1 - c0, min(step, src.height - r0)))
            out[np.ix_(lr[sel], lc)] = arr[np.ix_(pr[sel] - r0, pc - c0)]
        # Plymouth County full-res clip
        win = from_bounds(*focus_bbox_5070(), transform=src.transform)
        assert abs(win.col_off - round(win.col_off)) < 1e-6 and abs(win.row_off - round(win.row_off)) < 1e-6
        win = win.round_offsets().round_lengths()
        foc = src.read(1, window=win)
        write_focus_tif(foc, src.window_transform(win), year, URL.format(y=year))
    tmp = lattice_path(year) + ".tmp.npy"
    np.save(tmp, out)
    os.replace(tmp, lattice_path(year))
    return out


def main():
    keep = "--keep" in sys.argv
    threads = 4
    if "--threads" in sys.argv:
        threads = int(sys.argv[sys.argv.index("--threads") + 1])
    years = [int(a) for a in sys.argv[1:] if a.isdigit() and len(a) == 4] or NASS_YEARS
    os.makedirs(ZDIR, exist_ok=True)
    for y in years:
        if os.path.exists(lattice_path(y)) and os.path.exists(focus_path(y)):
            print(f"{y}: cached lattice + focus clip")
            continue
        t0 = time.time()
        tif = fetch_tif(y, threads)
        lat = sample_lattice(tif, y)
        print(f"{y}: lattice sampled ({(lat > 0).mean():.3f} non-zero) in {time.time() - t0:.0f}s total", flush=True)
        if not keep:
            os.remove(tif); os.remove(tif + ".done")


if __name__ == "__main__":
    main()
