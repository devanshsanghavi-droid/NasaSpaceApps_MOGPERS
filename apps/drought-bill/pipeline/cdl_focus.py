"""Plymouth County, Iowa (19149) field samples from full-resolution (30 m) CDL 2008-2024.

Inputs: data/raw/cdl/focus/cdl_<year>_19149.tif (written by cdl_pc_fetch.py and cdl_nass_fetch.py).
Outputs: data/processed/cdl_focus_fields.parquet and web/data/focus_fields.json.

Field sample rule: candidate centres on a regular grid (900 m; densified only if < 300 qualify). A candidate is
kept if its whole 5x5 block (150 m x 150 m) lies inside the county and, in >= 14 of the 17 years,
(a) >= 22 of the 25 block pixels share the centre's crop class and (b) the centre is a cropland class.

Usage: python pipeline/cdl_focus.py
"""
import json, os, sys
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
from pyproj import Transformer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import PROC, WEBDATA, YEARS, FOCUS_FIPS, focus_path, load_counties  # noqa: E402
from cdl_metrics import (LUT, LETTER, CLASS_NAMES, CROPLAND, ROT_CLASSES, window_metrics,  # noqa: E402
                         rotation_class_codes)

HALF = 2           # 5x5 block
MIN_SAME = 22      # of 25
MIN_YEARS = 14     # of 17


def load_stack():
    arrs, tr0, shp0 = [], None, None
    for y in YEARS:
        with rasterio.open(focus_path(y)) as src:
            if tr0 is None:
                tr0, shp0 = src.transform, src.shape
            assert src.transform == tr0 and src.shape == shp0, (y, src.transform, tr0)
            arrs.append(src.read(1))
    return np.stack(arrs), tr0


def alignment_check(raw, tr):
    """PC (2021) vs NASS (2022) grid alignment: agreement of stable non-crop classes at 0 vs 1 px shift."""
    a, b = raw[YEARS.index(2021)], raw[YEARS.index(2022)]
    stable = lambda z: np.isin(z, [111, 121, 122, 123, 124, 141])  # noqa: E731
    out = {}
    for name, (dy, dx) in {"0px": (0, 0), "1px_x": (0, 1), "1px_y": (1, 0)}.items():
        A = stable(a[dy:, dx:]); B = stable(b[:b.shape[0] - dy, :b.shape[1] - dx])
        out[name] = float((A & B).sum() / max((A | B).sum(), 1))
    return out


def main():
    raw, tr = load_stack()
    cls = LUT[raw]                                              # (T, H, W)
    T, H, Wd = cls.shape
    print("alignment IoU (stable classes, 2021 PC vs 2022 NASS):", alignment_check(raw, tr))
    g = load_counties()
    poly = g[g.fips == FOCUS_FIPS].to_crs(5070)
    name = poly.NAME.iloc[0] + " County, " + poly.STUSPS.iloc[0]
    inside = rasterio.features.rasterize([(poly.geometry.iloc[0], 1)], out_shape=(H, Wd), transform=tr,
                                         fill=0, dtype="uint8").astype(bool)
    offs = [(dy, dx) for dy in range(-HALF, HALF + 1) for dx in range(-HALF, HALF + 1)]
    for step in (30, 20, 15, 10):                               # pixels: 900, 600, 450, 300 m
        rr, cc = np.meshgrid(np.arange(HALF + step // 2, H - HALF, step), np.arange(HALF + step // 2, Wd - HALF, step),
                             indexing="ij")
        rr, cc = rr.ravel(), cc.ravel()
        ok = np.ones(rr.size, bool)
        for dy, dx in offs:
            ok &= inside[rr + dy, cc + dx]
        rr, cc = rr[ok], cc[ok]
        centre = cls[:, rr, cc]                                 # (T, n)
        same = np.zeros(centre.shape, np.int16)
        for dy, dx in offs:
            same += cls[:, rr + dy, cc + dx] == centre
        homog = same >= MIN_SAME
        cropy = CROPLAND[centre]
        good_years = (homog & cropy).sum(0)
        keep = good_years >= MIN_YEARS
        print(f"grid step {step * 30} m: {ok.sum()} candidates inside county, {keep.sum()} field samples")
        if keep.sum() >= 300:
            break
    rr, cc, centre, good_years = rr[keep], cc[keep], centre[:, keep], good_years[keep]
    xs = tr.c + (cc + 0.5) * tr.a
    ys = tr.f + (rr + 0.5) * tr.e
    lon, lat = Transformer.from_crs(5070, 4326, always_xy=True).transform(xs, ys)
    seq = ["".join(LETTER[centre[:, i]]) for i in range(centre.shape[1])]
    detail = ["".join(CLASS_NAMES[k] for k in centre[:, i]) for i in range(centre.shape[1])]
    w = centre[YEARS.index(2020):YEARS.index(2024) + 1]
    m5 = window_metrics(w)
    rc5 = rotation_class_codes(m5)
    mf = window_metrics(centre)
    rcf = rotation_class_codes(mf)
    df = pd.DataFrame({
        "id": [f"p{i + 1:04d}" for i in range(len(seq))],
        "fips": FOCUS_FIPS,
        "lon": np.round(lon, 5), "lat": np.round(lat, 5),
        "x_5070": xs, "y_5070": ys,
        "seq": seq,
        "seq_detail": detail,
        "rotation_class": [ROT_CLASSES[k] for k in rc5],
        "div_shannon_2020_2024": np.round(m5["div"], 4).astype("float32"),
        "n_crops_2020_2024": m5["ncrop"].astype("int8"),
        "rotation_class_2008_2024": [ROT_CLASSES[k] for k in rcf],
        "div_shannon_2008_2024": np.round(mf["div"], 4).astype("float32"),
        "n_crops_2008_2024": mf["ncrop"].astype("int8"),
        "n_homog_crop_years": good_years.astype("int8"),
    })
    os.makedirs(PROC, exist_ok=True)
    df.to_parquet(os.path.join(PROC, "cdl_focus_fields.parquet"), index=False)
    js = {"county": {"fips": FOCUS_FIPS, "name": name}, "years": YEARS,
          "fields": [{"id": r.id, "lon": float(r.lon), "lat": float(r.lat), "seq": r.seq,
                      "rotation_class": r.rotation_class,
                      "div5": None if np.isnan(r.div_shannon_2020_2024) else round(float(r.div_shannon_2020_2024), 3),
                      "ncrop5": int(r.n_crops_2020_2024)} for r in df.itertuples()]}
    os.makedirs(WEBDATA, exist_ok=True)
    with open(os.path.join(WEBDATA, "focus_fields.json"), "w") as f:
        json.dump(js, f, separators=(",", ":"))
    print(f"wrote {len(df)} field samples")
    print(df.rotation_class.value_counts().to_string())
    print(df.seq.str[-5:].value_counts().head(10).to_string())


if __name__ == "__main__":
    main()
