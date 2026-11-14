"""conf module: assemble data/confounders.parquet and data/weather_annual.parquet.

Inputs (written by conf_terrain.py, conf_soils.py, conf_weather.py, conf_imerg.py):
  data/raw/conf/terrain_points.parquet, data/raw/conf/soils_points.parquet,
  data/raw/power/weather_annual_power.parquet, data/raw/conf/imerg_annual.parquet (optional)
Re-run all: .venv/bin/python pipeline/conf_run_all.py   (or this script alone after the four above)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
RAWC = ROOT / "data" / "raw" / "conf"
REGION = json.loads((ROOT / "data" / "region.json").read_text())
DLAT, DLON = 0.5, 0.625


def main():
    g = REGION["grid"]
    rows, cols = np.meshgrid(np.arange(g["nrows"]), np.arange(g["ncols"]), indexing="ij")
    rows = rows.ravel(); cols = cols.ravel()
    pts = pd.DataFrame(dict(grid_id=rows * g["ncols"] + cols,
                            x=g["x0"] + cols * g["spacing_m"], y=g["y0"] - rows * g["spacing_m"]))
    lon, lat = Transformer.from_crs("EPSG:32615", "EPSG:4326", always_xy=True).transform(pts.x.values, pts.y.values)
    pts["field_id"] = ["f%05d" % i for i in pts.grid_id]

    daily_cells = pd.read_parquet(ROOT / "data" / "weather_daily_power.parquet",
                                  columns=["power_cell_id", "cell_lat", "cell_lon"]).drop_duplicates()
    cl = daily_cells.cell_lat.values; co = daily_cells.cell_lon.values
    # nearest cell centre in normalised grid units (== containing MERRA-2 cell)
    d = ((lat[:, None] - cl[None, :]) / DLAT) ** 2 + ((lon[:, None] - co[None, :]) / DLON) ** 2
    pts["power_cell_id"] = daily_cells.power_cell_id.values[d.argmin(1)]

    ter = pd.read_parquet(RAWC / "terrain_points.parquet").drop(columns=["field_id"])
    soi = pd.read_parquet(RAWC / "soils_points.parquet").drop(columns=["field_id"])
    soi = soi.rename(columns={"slope_r": "ssurgo_slope_r", "muname": "ssurgo_muname",
                              "compname": "ssurgo_compname", "comppct_r": "ssurgo_comppct_r",
                              "hzname": "surf_hzname", "hzdepb_r": "surf_hz_bottom_cm"}).drop(columns=["hzdept_r"])
    conf = pts[["field_id", "grid_id"]].merge(ter, on="grid_id").merge(soi, on="grid_id")
    conf["power_cell_id"] = pts.power_cell_id.values
    main_cols = ["field_id", "grid_id", "elev_m", "slope_pct", "curvature", "twi", "flowacc", "mukey", "aws0_100",
                 "soc0_30", "nccpi3corn", "nccpi3soy", "droughty", "rootznaws", "kwfact", "om_r", "drainagecl",
                 "hydgrp", "clay_pct", "sand_pct", "power_cell_id"]
    extra = [c for c in conf.columns if c not in main_cols]
    conf = conf[main_cols + extra]
    conf["droughty"] = conf.droughty.astype("Int8")
    assert len(conf) == 50850 and conf.field_id.is_unique
    conf.to_parquet(ROOT / "data" / "confounders.parquet", index=False)
    print("confounders", conf.shape)
    print(conf.isna().mean().round(4).to_string())

    ann = pd.read_parquet(ROOT / "data" / "raw" / "power" / "weather_annual_power.parquet")
    imf = RAWC / "imerg_annual.parquet"
    imerg_cols = ["imerg_max30min_amj", "imerg_r_factor", "imerg_n_days_sampled"]
    if imf.exists():
        im = pd.read_parquet(imf)[["power_cell_id", "year"] + imerg_cols]
        ann = ann.merge(im, on=["power_cell_id", "year"], how="left")
    else:
        for c in imerg_cols:
            ann[c] = np.nan
    ann = ann.sort_values(["power_cell_id", "year"]).reset_index(drop=True)
    ann.to_parquet(ROOT / "data" / "weather_annual.parquet", index=False)
    print("weather_annual", ann.shape)
    print(ann.describe().T[["count", "mean", "min", "max"]].round(2).to_string())


if __name__ == "__main__":
    main()
