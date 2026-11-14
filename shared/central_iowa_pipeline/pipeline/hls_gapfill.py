"""COUNTERFIELD hls module, step 2 (gap fill): HLS v2 on Planetary Computer has (almost) no T15TVG scenes before 2020
(hls2-s30 starts 2020; hls2-l30 has 15 scenes in 2017-2018). To keep the 2016-2024 panel usable, this samples the two
upstream surface-reflectance products HLS itself is built from, for 2016-01-01..2019-12-31 only:
  * landsat-c2-l2   (Landsat 8 OLI Collection 2 Level-2 SR, Tier 1, eo:cloud_cover < 60)  -> product 'LC08L2', sensor 'L30'
  * sentinel-2-l2a  (Sentinel-2 MSI L2A Sen2Cor, MGRS tile 15TVG, eo:cloud_cover < 60)   -> product 'S2L2A',  sensor 'S30'
S2 reflectances get the HLS v2 bandpass adjustment (slope/offset read from HLS v2 S30 file tags) so they are OLI-like
like HLS S30. No BRDF (NBAR) normalisation is applied to either gap-fill product. Landsat dates that already have an
HLS2 L30 scene are skipped. Checkpoints go to the same data/raw/hls/scenes/ folder.

Usage: .venv/bin/python pipeline/hls_gapfill.py [--limit N] [--workers 12] [--refresh-items] [--only s2|ls]
"""
import argparse, json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import numpy as np
import pandas as pd
import pystac_client, planetary_computer, rasterio
from rasterio.windows import from_bounds

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hls_common import (RAW, STAC_URL, REGION, GDAL_ENV, grid, read_overview, pixel_index, write_scene,
                        scene_done, build_rows, unsigned)

ITEMS_CACHE = RAW / "items_gapfill.json"
LS_BANDS = dict(blue="blue", green="green", red="red", nir="nir08", swir1="swir16", swir2="swir22")
S2_BANDS = dict(blue="B02", green="B03", red="B04", nir="B8A", swir1="B11", swir2="B12")
S2_10M = {"B02", "B03", "B04"}
# HLS v2 bandpass adjustment (OLI-like = slope * MSI + offset), copied from HLS v2 S30 GeoTIFF tags
# ('MSI band XX bandpass adjustment slope and offset') of T15TVG scenes from Sentinel-2A and Sentinel-2B.
BANDPASS = {
    "S2A": dict(blue=(0.9778, -0.0040), green=(1.0053, -0.0009), red=(0.9765, 0.0009), nir=(0.9983, -0.0001),
                swir1=(0.9987, -0.0011), swir2=(1.0030, -0.0012)),
    "S2B": dict(blue=(0.9778, -0.0040), green=(1.0075, -0.0008), red=(0.9761, 0.0010), nir=(0.9966, 0.0000),
                swir1=(1.0000, -0.0003), swir2=(0.9867, 0.0004)),
}
TB = REGION["tile_bounds_utm"]


def list_items(refresh=False):
    if ITEMS_CACHE.exists() and not refresh:
        return json.loads(ITEMS_CACHE.read_text())
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    bb = REGION["tile_bounds_lonlat"]
    hls_items = json.loads((RAW / "items_hls2.json").read_text())
    hls_l30_dates = {pd.Timestamp(i["datetime"]).strftime("%Y-%m-%d") for i in hls_items if i["sensor"] == "L30"}
    out = []
    # Landsat 8 C2 L2, Tier 1
    for it in c.search(collections=["landsat-c2-l2"], bbox=bb, datetime="2016-01-01/2019-12-31",
                       query={"platform": {"in": ["landsat-8"]}, "eo:cloud_cover": {"lt": 60}}).items():
        if it.properties.get("landsat:collection_category") != "T1":
            continue
        d = it.datetime.strftime("%Y-%m-%d")
        if d in hls_l30_dates:
            continue
        out.append(dict(item_id=it.id, collection="landsat-c2-l2", sensor="L30", product="LC08L2",
                        datetime=it.datetime.isoformat(), cloud_cover=it.properties.get("eo:cloud_cover"),
                        assets={k: unsigned(it.assets[k].href) for k in list(LS_BANDS.values()) + ["qa_pixel"]}))
    # Sentinel-2 L2A on MGRS 15TVG; keep latest processing per datatake
    s2 = {}
    for it in c.search(collections=["sentinel-2-l2a"], bbox=bb, datetime="2016-01-01/2019-12-31",
                       query={"s2:mgrs_tile": {"eq": "15TVG"}, "eo:cloud_cover": {"lt": 60}}).items():
        key = "_".join(it.id.split("_")[:4])
        if key not in s2 or it.id > s2[key].id:
            s2[key] = it
    for it in s2.values():
        bl = float(it.properties.get("s2:processing_baseline", "0"))
        boa_offset = -1000 if bl >= 4.0 else 0  # BOA_ADD_OFFSET from baseline 04.00 on (incl. 2023 reprocessing 05.00)
        out.append(dict(item_id=it.id, collection="sentinel-2-l2a", sensor="S30", product="S2L2A",
                        platform=it.id[:3], baseline=bl, boa_offset=boa_offset, datetime=it.datetime.isoformat(),
                        cloud_cover=it.properties.get("eo:cloud_cover"),
                        assets={k: unsigned(it.assets[k].href) for k in list(S2_BANDS.values()) + ["SCL"]}))
    out.sort(key=lambda d: d["datetime"])
    ITEMS_CACHE.write_text(json.dumps(out, indent=0))
    return out


def read_window(href, bounds, ov_level=None, retries=7):
    """Read only the part of band 1 covering `bounds` (full res, or overview `ov_level`)."""
    last = None
    for a in range(retries):
        try:
            url = planetary_computer.sign(unsigned(href))
            kw = {} if ov_level is None else {"OVERVIEW_LEVEL": ov_level}
            with rasterio.Env(**GDAL_ENV), rasterio.open(url, **kw) as ds:
                w = from_bounds(*bounds, transform=ds.transform).round_offsets().round_lengths()
                w = w.intersection(rasterio.windows.Window(0, 0, ds.width, ds.height))
                arr = ds.read(1, window=w)
                return arr, ds.window_transform(w)
        except Exception as e:
            last = e
            time.sleep(min(60, 2 ** a))
    raise RuntimeError(f"window read failed: {unsigned(href)} :: {last}")


def neighbourhood_all(mask2d, r, c, inside):
    """True where the 3x3 neighbourhood around (r, c) is entirely True (edges count as False)."""
    H, W = mask2d.shape
    ok = inside.copy()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            rr = r + dr; cc = c + dc
            ins = (rr >= 0) & (rr < H) & (cc >= 0) & (cc < W)
            ok &= ins & mask2d[np.clip(rr, 0, H - 1), np.clip(cc, 0, W - 1)]
    return ok


def process(it, g):
    t0 = time.time()
    date = pd.Timestamp(it["datetime"]).tz_convert(None).normalize()
    x = g["x"].values; y = g["y"].values
    if it["product"] == "LC08L2":
        qa, qtr = read_window(it["assets"]["qa_pixel"], TB)
        r, c, ins = pixel_index(qtr, x, y, qa.shape)
        fill = (qa & 1) == 1
        clr = ~fill & ((qa & 0b111010) == 0)  # bits 1 dilated cloud, 3 cloud, 4 shadow, 5 snow all 0
        clear = neighbourhood_all(clr, r, c, ins)
        valid = ins & ~fill[r, c]
        water_all = ((qa[r, c] >> 7) & 1) == 1
        bands, ov = LS_BANDS, 0
    else:
        scl, qtr, _ = read_overview(it["assets"]["SCL"], ov_level=None)  # full-res 20 m, categorical
        r, c, ins = pixel_index(qtr, x, y, scl.shape)
        clear = neighbourhood_all(np.isin(scl, (4, 5, 6)), r, c, ins)  # vegetation, bare soil, water
        valid = ins & (scl[r, c] != 0)
        water_all = scl[r, c] == 6
        bands = S2_BANDS
    meta = dict(item_id=it["item_id"], date=str(date.date()), datetime=it["datetime"], sensor=it["sensor"],
                product=it["product"], collection=it["collection"], cloud_cover=it["cloud_cover"],
                n_valid=int(valid.sum()), n_fmask_clear=int(clear.sum()), n_clear=0, n_bad_refl=0, n_water=0)
    empty = {k: np.zeros(0, np.int16) for k in bands}
    if clear.sum() == 0:
        write_scene(it["item_id"], build_rows(g, clear, date, it["sensor"], it["product"], empty,
                                               np.zeros(0, bool), np.zeros(0, np.int8)), meta)
        return meta, time.time() - t0
    refl = {}
    for name, key in bands.items():
        if it["product"] == "LC08L2":
            a, tr = read_window(it["assets"][key], TB, ov_level=0)            # ~60 m overview, tile window only
            rr, cc, ii = pixel_index(tr, x, y, a.shape)
            dn = a[rr, cc].astype(np.float64)
            v = np.where((dn > 0) & ii, dn * 0.0000275 - 0.2, np.nan)
        else:
            lvl = 1 if key in S2_10M else 0                                   # both -> 40 m overview
            a, tr, _ = read_overview(it["assets"][key], ov_level=lvl)
            rr, cc, ii = pixel_index(tr, x, y, a.shape)
            dn = a[rr, cc].astype(np.float64)
            s, o = BANDPASS[it["platform"]][name]
            v = np.where((dn > 0) & ii, s * ((dn + it["boa_offset"]) / 10000.0) + o, np.nan)
        refl[name] = v
    ok = clear.copy()
    for v in refl.values():
        ok &= np.isfinite(v) & (v > 0)
    meta["n_bad_refl"] = int(clear.sum() - ok.sum())
    water = water_all[ok]
    meta["n_clear"] = int(ok.sum()); meta["n_water"] = int(water.sum())
    refl_i = {k: np.round(np.clip(v[ok], 0, 3.2767) * 1e4).astype(np.int16) for k, v in refl.items()}
    df = build_rows(g, ok, date, it["sensor"], it["product"], refl_i, water, np.full(int(ok.sum()), -1, np.int8))
    write_scene(it["item_id"], df, meta)
    return meta, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--refresh-items", action="store_true")
    ap.add_argument("--only", choices=["s2", "ls"], default=None)
    a = ap.parse_args()
    items = list_items(a.refresh_items)
    print(f"{len(items)} gap-fill items (LC08L2={sum(i['product']=='LC08L2' for i in items)}, "
          f"S2L2A={sum(i['product']=='S2L2A' for i in items)})", flush=True)
    todo = [i for i in items if not scene_done(i["item_id"])]
    if a.only:
        todo = [i for i in todo if i["product"] == {"s2": "S2L2A", "ls": "LC08L2"}[a.only]]
    if a.limit:
        todo = todo[:a.limit]
    print(f"{len(todo)} to process", flush=True)
    g = grid()
    t0 = time.time(); done = 0; fails = []
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(process, it, g): it for it in todo}
        for f in as_completed(futs):
            it = futs[f]
            try:
                meta, dtm = f.result(); done += 1
                print(f"[{done}/{len(todo)}] {it['item_id']} cc={it['cloud_cover']} valid={meta['n_valid']} clear={meta['n_clear']} {dtm:.1f}s elapsed={time.time()-t0:.0f}s", flush=True)
            except Exception as e:
                fails.append((it["item_id"], repr(e)))
                print(f"FAIL {it['item_id']}: {e}", flush=True)
    print(f"done {done}, failed {len(fails)} in {time.time()-t0:.0f}s", flush=True)
    if fails:
        (RAW / "failures_gapfill.json").write_text(json.dumps(fails, indent=1))


if __name__ == "__main__":
    main()
