"""COUNTERFIELD hls module, step 1: sample HLS v2 (hls2-l30, hls2-s30; tile T15TVG; eo:cloud_cover < 60;
2016-01-01..2024-12-31) at every grid point, one checkpoint per scene under data/raw/hls/scenes/.

Usage: .venv/bin/python pipeline/hls_fetch.py [--limit N] [--workers 12] [--refresh-items]
"""
import argparse, json, sys, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import pystac_client, planetary_computer

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from hls_common import RAW, STAC_URL, grid, read_overview, pixel_index, write_scene, scene_done, build_rows

BANDS = {  # common name -> asset key
    "L30": dict(blue="B02", green="B03", red="B04", nir="B05", swir1="B06", swir2="B07"),
    "S30": dict(blue="B02", green="B03", red="B04", nir="B8A", swir1="B11", swir2="B12"),
}
ITEMS_CACHE = RAW / "items_hls2.json"


def list_items(refresh=False):
    if ITEMS_CACHE.exists() and not refresh:
        return json.loads(ITEMS_CACHE.read_text())
    c = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    out = []
    for col, sensor in [("hls2-l30", "L30"), ("hls2-s30", "S30")]:
        s = c.search(collections=[col], bbox=[-93.6, 41.9, -93.5, 42.0], datetime="2016-01-01/2024-12-31",
                     query={"eo:cloud_cover": {"lt": 60}})
        for it in s.items():
            if "T15TVG" not in it.id:
                continue
            out.append(dict(item_id=it.id, collection=col, sensor=sensor,
                            datetime=it.datetime.isoformat(), cloud_cover=it.properties.get("eo:cloud_cover"),
                            assets={k: it.assets[k].href.split("?")[0] for k in list(BANDS[sensor].values()) + ["Fmask"]}))
    out.sort(key=lambda d: d["datetime"])
    RAW.mkdir(parents=True, exist_ok=True)
    ITEMS_CACHE.write_text(json.dumps(out, indent=0))
    return out


def process(it, g):
    t0 = time.time()
    sensor = it["sensor"]
    date = pd.Timestamp(it["datetime"]).tz_convert(None).normalize() if pd.Timestamp(it["datetime"]).tzinfo else pd.Timestamp(it["datetime"]).normalize()
    fm, tr, nod = read_overview(it["assets"]["Fmask"])
    r, c, inside = pixel_index(tr, g["x"].values, g["y"].values, fm.shape)
    q = fm[r, c]
    valid = inside & (q != 255)
    clear = valid & ((q & 0b11110) == 0)  # bits 1 cloud, 2 adjacent, 3 shadow, 4 snow/ice all 0
    meta = dict(item_id=it["item_id"], date=str(date.date()), datetime=it["datetime"], sensor=sensor,
                product="HLS2", collection=it["collection"], cloud_cover=it["cloud_cover"],
                n_valid=int(valid.sum()), n_fmask_clear=int(clear.sum()), n_clear=0, n_bad_refl=0, n_water=0)
    if clear.sum() == 0:
        write_scene(it["item_id"], build_rows(g, clear, date, sensor, "HLS2",
                                               {k: np.zeros(0, np.int16) for k in BANDS[sensor]},
                                               np.zeros(0, bool), np.zeros(0, np.int8)), meta)
        return meta, time.time() - t0
    refl = {}
    for name, key in BANDS[sensor].items():
        a, tr_b, nod_b = read_overview(it["assets"][key])
        assert a.shape == fm.shape and tr_b == tr, (key, a.shape, tr_b)
        refl[name] = a[r, c]
    ok = clear.copy()
    for v in refl.values():
        ok &= (v != -9999) & (v > 0)  # drop fill and non-positive reflectance
    meta["n_bad_refl"] = int(clear.sum() - ok.sum())
    water = ((q[ok] >> 5) & 1) == 1
    aerosol = (q[ok] >> 6) & 0b11
    meta["n_clear"] = int(ok.sum()); meta["n_water"] = int(water.sum())
    df = build_rows(g, ok, date, sensor, "HLS2", {k: v[ok] for k, v in refl.items()}, water, aerosol)
    write_scene(it["item_id"], df, meta)
    return meta, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--refresh-items", action="store_true")
    a = ap.parse_args()
    items = list_items(a.refresh_items)
    print(f"{len(items)} HLS2 items (L30={sum(i['sensor']=='L30' for i in items)}, S30={sum(i['sensor']=='S30' for i in items)})", flush=True)
    todo = [i for i in items if not scene_done(i["item_id"])]
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
                print(f"[{done}/{len(todo)}] {it['item_id']} cc={it['cloud_cover']} clear={meta['n_clear']} {dtm:.1f}s elapsed={time.time()-t0:.0f}s", flush=True)
            except Exception as e:
                fails.append((it["item_id"], repr(e)))
                print(f"FAIL {it['item_id']}: {e}", flush=True)
    print(f"done {done}, failed {len(fails)} in {time.time()-t0:.0f}s", flush=True)
    if fails:
        (RAW / "failures_hls2.json").write_text(json.dumps(fails, indent=1))


if __name__ == "__main__":
    main()
