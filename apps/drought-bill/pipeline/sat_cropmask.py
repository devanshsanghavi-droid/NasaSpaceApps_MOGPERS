"""sat module: cropland share per MODIS ~927 m pixel (overview level 1 of MOD13Q1) from USDA CDL.

Input: the `cdl` module's cached CDL samples data/raw/cdl/lattice_<year>.npy (uint8 CDL codes on a fixed 240 m lattice
in EPSG:5070; see pipeline/cdl_common.py). Read only. Preferred year 2016, else the nearest available year.
Each lattice point is projected to the MODIS sinusoidal grid and counted in its 927 m pixel (about 14 points per pixel).
crop_share = share of lattice points whose CDL code is a cultivated crop: codes 1-60, 66-80, 200-255 (row crops, small
grains, hay/alfalfa, vegetables, orchards, double crops). Fallow (61), grass/pasture (62, 171, 176, 181), forest,
water, developed and wetland codes are not crop.
Output: data/raw/modis/cropmask_hHHvVV.npz {crop_share, n_pts, cdl_year} for the tiles used by sat_modis.py.

Run: /home/user/venv-db/bin/python pipeline/sat_cropmask.py
"""
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cdl_common import RAW as CDL_RAW, X0 as LX0, YTOP, SPACING  # noqa: E402
from sat_modis import RAW, X0, Y0, T, SINU, NPX  # noqa: E402

TILES = [(9, 5), (10, 4), (10, 5), (11, 4), (11, 5), (12, 4)]
PREF = [2016, 2015, 2017, 2014, 2018, 2013, 2019, 2012, 2020, 2011, 2021, 2010, 2022, 2009, 2023, 2008, 2024]


def main():
    year = next((y for y in PREF if (Path(CDL_RAW) / f"lattice_{y}.npy").exists()), None)
    if year is None:
        print("no CDL lattice available yet")
        return 1
    lat = np.load(Path(CDL_RAW) / f"lattice_{year}.npy", mmap_mode="r")
    print("CDL lattice", year, lat.shape)
    crop_code = np.zeros(256, bool)
    crop_code[1:61] = True
    crop_code[66:81] = True
    crop_code[200:256] = True
    tr = Transformer.from_crs(5070, SINU, always_xy=True)
    acc = {t: (np.zeros(NPX * NPX), np.zeros(NPX * NPX)) for t in TILES}
    res = T / NPX
    for r0 in range(0, lat.shape[0], 500):
        blk = np.asarray(lat[r0:r0 + 500])
        rr, cc = np.nonzero(blk > 0)
        if rr.size == 0:
            continue
        code = blk[rr, cc]
        x = LX0 + SPACING * cc.astype(np.float64)
        y = YTOP - SPACING * (rr + r0).astype(np.float64)
        sx, sy = tr.transform(x, y)
        h = np.floor((sx - X0) / T).astype(int)
        v = np.floor((Y0 - sy) / T).astype(int)
        col = np.floor((sx - (X0 + h * T)) / res).astype(int)
        row = np.floor(((Y0 - v * T) - sy) / res).astype(int)
        isc = crop_code[code]
        for t in TILES:
            m = (h == t[0]) & (v == t[1])
            if not m.any():
                continue
            k = row[m] * NPX + col[m]
            acc[t][0][:] += np.bincount(k, minlength=NPX * NPX)
            acc[t][1][:] += np.bincount(k, weights=isc[m], minlength=NPX * NPX)
    for t, (n, c) in acc.items():
        with np.errstate(invalid="ignore", divide="ignore"):
            share = np.where(n > 0, c / n, 0.0).reshape(NPX, NPX).astype(np.float32)
        np.savez_compressed(RAW / f"cropmask_h{t[0]:02d}v{t[1]:02d}.npz", crop_share=share,
                            n_pts=n.reshape(NPX, NPX).astype(np.uint16), cdl_year=year)
        print(f"h{t[0]:02d}v{t[1]:02d}: pixels with points {int((n > 0).sum())}, crop>=0.5 {int((share >= 0.5).sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
