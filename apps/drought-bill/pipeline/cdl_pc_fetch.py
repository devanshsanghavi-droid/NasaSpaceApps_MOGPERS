"""CDL 2008-2021 from Microsoft Planetary Computer (usda-cdl, usda_cdl:type=cropland), sampled on the fixed lattice.

The COG overviews are majority/mode-resampled (tested: an overview value is always one of the 2x2 block values but
only matches a fixed pixel offset ~85-96% of the time), so they are NOT used. Each 3000x3000 tile is read at full
30 m resolution and the lattice points (pixel centres) are picked out exactly.

Cache: data/raw/cdl/pc_tiles/<year>/<item id>.npz (lattice row/col indices + values; plus the Plymouth County
window if the tile touches it). Then per year: data/raw/cdl/lattice_<year>.npy and focus/cdl_<year>_19149.tif.

Usage: python pipeline/cdl_pc_fetch.py [--threads N]
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import rasterio
from rasterio.transform import Affine, from_origin
from rasterio.windows import from_bounds
import planetary_computer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import (RAW, STAC, PC_YEARS, NX, NY, lattice_index_for_raster, lattice_path, load_counties,  # noqa
                        focus_bbox_5070, focus_path, write_focus_tif)

ITEMS_JSON = os.path.join(RAW, "pc_items.json")
TILES = os.path.join(RAW, "pc_tiles")


def list_items():
    if os.path.exists(ITEMS_JSON):
        return json.load(open(ITEMS_JSON))
    import pystac_client
    from shapely.geometry import box
    g = load_counties()
    region = g.to_crs(5070).union_all().buffer(1000)
    lon0, lat0, lon1, lat1 = g.total_bounds
    c = pystac_client.Client.open(STAC)
    s = c.search(collections=["usda-cdl"], bbox=[lon0 - 0.5, lat0 - 0.5, lon1 + 0.5, lat1 + 0.5],
                 query={"usda_cdl:type": {"eq": "cropland"}})
    out = []
    for it in s.items():
        t = it.properties["proj:transform"]
        h, w = it.properties["proj:shape"]
        bx = box(t[2], t[5] + t[4] * h, t[2] + t[0] * w, t[5])
        if not bx.intersects(region):
            continue
        out.append(dict(id=it.id, year=int(it.properties["start_datetime"][:4]), href=it.assets["cropland"].href,
                        transform=t, shape=[h, w]))
    tmp = ITEMS_JSON + ".tmp"
    json.dump(out, open(tmp, "w"))
    os.replace(tmp, ITEMS_JSON)
    return out


def tile_cache(it):
    return os.path.join(TILES, str(it["year"]), it["id"] + ".npz")


def fetch_tile(it):
    p = tile_cache(it)
    if os.path.exists(p):
        return it["id"], "cached"
    fb = focus_bbox_5070()
    for k in range(6):
        try:
            href = planetary_computer.sign(it["href"])  # re-signed on every attempt (SAS tokens expire)
            with rasterio.open(href) as src:
                assert src.crs.to_epsg() == 5070
                arr = src.read(1)
                tr = src.transform
            break
        except Exception as e:
            print(f"  {it['id']} retry {k}: {str(e)[:200]}", flush=True)
            time.sleep(5 * (k + 1))
    else:
        raise RuntimeError(f"failed {it['id']}")
    lr, lc, pr, pc = lattice_index_for_raster(tr, arr.shape[0], arr.shape[1])
    vals = arr[np.ix_(pr, pc)]
    extra = {}
    b = rasterio.transform.array_bounds(arr.shape[0], arr.shape[1], tr)  # (west, south, east, north)
    if not (b[2] <= fb[0] or b[0] >= fb[2] or b[3] <= fb[1] or b[1] >= fb[3]):
        win = from_bounds(*fb, transform=tr).round_offsets().round_lengths()
        r0, c0 = int(win.row_off), int(win.col_off)
        rs, cs = max(r0, 0), max(c0, 0)
        re, ce = min(r0 + int(win.height), arr.shape[0]), min(c0 + int(win.width), arr.shape[1])
        extra = dict(focus=arr[rs:re, cs:ce], focus_off=np.array([rs - r0, cs - c0]))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp.npz"
    np.savez_compressed(tmp, lr=lr.astype(np.int32), lc=lc.astype(np.int32), vals=vals, **extra)
    os.replace(tmp, p)
    return it["id"], "ok"


def assemble(year, items):
    if os.path.exists(lattice_path(year)) and os.path.exists(focus_path(year)):
        return
    out = np.zeros((NY, NX), np.uint8)
    fb = focus_bbox_5070()
    fw, fh = int(round((fb[2] - fb[0]) / 30)), int(round((fb[3] - fb[1]) / 30))
    foc = np.zeros((fh, fw), np.uint8)
    ids = []
    for it in items:
        z = np.load(tile_cache(it))
        sub = out[np.ix_(z["lr"], z["lc"])]
        v = z["vals"]
        out[np.ix_(z["lr"], z["lc"])] = np.where(sub == 0, v, sub)
        if "focus" in z:
            f = z["focus"]; ro, co = z["focus_off"]
            blk = foc[ro:ro + f.shape[0], co:co + f.shape[1]]
            foc[ro:ro + f.shape[0], co:co + f.shape[1]] = np.where(blk == 0, f, blk)
            ids.append(it["id"])
    np.save(lattice_path(year) + ".tmp.npy", out)
    os.replace(lattice_path(year) + ".tmp.npy", lattice_path(year))
    write_focus_tif(foc, from_origin(fb[0], fb[3], 30, 30), year,
                    "planetary-computer usda-cdl cropland: " + ",".join(sorted(ids)))
    print(f"{year}: assembled lattice ({(out > 0).mean():.3f} non-zero), focus zero-frac {np.mean(foc == 0):.4f}",
          flush=True)


def main():
    threads = 4
    if "--threads" in sys.argv:
        threads = int(sys.argv[sys.argv.index("--threads") + 1])
    items = list_items()
    by = {}
    for it in items:
        by.setdefault(it["year"], []).append(it)
    print("PC years:", {y: len(v) for y, v in sorted(by.items())}, flush=True)
    todo = [it for y in PC_YEARS for it in by.get(y, []) if not os.path.exists(tile_cache(it))]
    print(f"{len(todo)} tiles to fetch", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(threads) as ex:
        futs = [ex.submit(fetch_tile, it) for it in todo]
        for i, f in enumerate(as_completed(futs)):
            f.result()
            if (i + 1) % 50 == 0:
                el = time.time() - t0
                print(f"  {i + 1}/{len(todo)} tiles, {el:.0f}s, eta {el / (i + 1) * (len(todo) - i - 1):.0f}s",
                      flush=True)
    for y in PC_YEARS:
        assemble(y, by[y])


if __name__ == "__main__":
    main()
