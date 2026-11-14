"""Focus area for the field drill-down: a contiguous block of Raccoon-basin HUC-12s inside ONE HLS MGRS tile.

Method
  1. Raccoon HUC-12s (data/processed/huc12.parquet, basin == 'raccoon') that lie entirely inside the HLS tile 15TUG
     (UTM 15N square 300000-409800 E, 4590240-4700040 N, read from the HLS v2 Fmask GeoTIFF header; 500 m margin).
  2. Row-crop share per HUC-12 from USDA CDL 2021 (Planetary Computer `usda-cdl`, cropland): corn + soy + other row.
  3. The focus set = the North Raccoon River mainstem HUC-10 0710000608 (Sac City -> Lake City -> Jefferson area,
     6 HUC-12s) plus the outlet HUC-12s of its three direct tributaries inside the tile (Camp Creek 060505,
     Lake Creek 060604/060605, Purgatory Creek 060702). The script checks contiguity, tile containment and area and
     prints the row-crop table so the choice can be audited against the alternatives.

Output: data/processed/focus_area.json {huc12s, names, hls_tile, bbox_lonlat, bbox_5070, area_km2, row_crop_share_2021,
reason, candidates:[...]}. huc12.parquet is not modified (its in_focus column is owned by the hydro module).
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
from rasterio.features import rasterize
from shapely.geometry import box
from shapely.ops import unary_union

from common import PROC
from fields_common import FOCUS_JSON, ROWCROP_LUT, pc_cdl_mosaic

TILE = "15TUG"
TILE_UTM = (300000.0, 4590240.0, 409800.0, 4700040.0)  # EPSG:32615, from HLS.L30.T15TUG.*.Fmask.tif bounds
FOCUS = ["071000060801", "071000060802", "071000060803", "071000060804", "071000060805", "071000060806",
         "071000060505", "071000060604", "071000060605", "071000060702"]
REASON = ("North Raccoon River middle reach below Sac City (HUC-10 0710000608: Sac, Calhoun, Carroll counties) plus "
          "the outlets of Camp, Lake and Purgatory creeks. This is the heavily tile-drained Des Moines Lobe headwater "
          "landscape whose drainage districts (Sac, Calhoun, Buena Vista counties) Des Moines Water Works sued in "
          "2015 over nitrate; the North Raccoon is the high-nitrate branch of the Raccoon. It is the most upstream "
          "contiguous block of the North Raccoon that fits entirely inside one HLS tile (15TUG; the tile's north edge "
          "is ~42.44 N, just below the Buena Vista headwaters), and its 2021 CDL row-crop share is among the highest "
          "in the basin (see candidates).")


def main():
    d = pd.read_parquet(PROC / "huc12.parquet")
    g = gpd.GeoDataFrame(d.drop(columns="geometry"), geometry=gpd.GeoSeries.from_wkb(d.geometry), crs=4326)
    g = g[g.basin == "raccoon"].copy()
    tile = box(*TILE_UTM)
    g["in_tile"] = g.to_crs(32615).within(tile.buffer(-500)).values
    cand = g[g.in_tile].to_crs(5070)
    b = cand.total_bounds
    cdl, tr = pc_cdl_mosaic(2021, (b[0] - 60, b[1] - 60, b[2] + 60, b[3] + 60))
    ids = {h: i + 1 for i, h in enumerate(cand.huc12)}
    lab = rasterize(((geom, ids[h]) for h, geom in zip(cand.huc12, cand.geometry)), out_shape=cdl.shape,
                    transform=tr, fill=0, dtype="int32")
    n_all = np.bincount(lab.ravel(), minlength=len(ids) + 1)
    n_row = np.bincount(lab.ravel(), weights=ROWCROP_LUT[cdl].ravel(), minlength=len(ids) + 1)
    cand["row_crop_2021"] = [n_row[ids[h]] / max(n_all[ids[h]], 1) for h in cand.huc12]
    cand["in_focus"] = cand.huc12.isin(FOCUS)
    show = cand[["huc12", "name", "area_km2", "row_crop_2021", "in_focus"]].sort_values("huc12")
    print(show.round(3).to_string(index=False))

    f = cand[cand.in_focus]
    assert len(f) == len(FOCUS), set(FOCUS) - set(f.huc12)
    u = unary_union(f.geometry.buffer(5))
    assert u.geom_type == "Polygon", f"focus not contiguous: {u.geom_type}"
    area = float(f.area.sum() / 1e6)
    assert 400 <= area <= 1200, area
    rc = float(np.sum(f.row_crop_2021 * f.area) / f.area.sum())
    others = cand[~cand.in_focus]
    rc_o = float(np.sum(others.row_crop_2021 * others.area) / others.area.sum())
    fl = f.to_crs(4326)
    bb = [round(float(v), 5) for v in fl.total_bounds]
    out = dict(huc12s=sorted(FOCUS), names={h: n for h, n in zip(f.huc12, f.name)}, hls_tile=TILE,
               hls_tile_bounds_utm15n=list(TILE_UTM), bbox_lonlat=bb,
               bbox_5070=[round(float(v), 1) for v in f.total_bounds], area_km2=round(area, 1),
               row_crop_share_2021=round(rc, 3), row_crop_share_2021_other_tile_hucs=round(rc_o, 3),
               reason=REASON,
               candidates=[dict(huc12=h, name=n, area_km2=round(float(a), 1), row_crop_2021=round(float(r), 3))
                           for h, n, a, r in zip(show.huc12, show.name, show.area_km2, show.row_crop_2021)],
               source_cdl="USDA NASS CDL 2021 via Planetary Computer usda-cdl (cropland)")
    FOCUS_JSON.write_text(json.dumps(out, indent=1))
    print(f"\nfocus: {len(FOCUS)} HUC-12s, {area:.0f} km2, row crop 2021 {rc:.1%} "
          f"(other in-tile Raccoon HUC-12s {rc_o:.1%}); bbox {bb}; wrote {FOCUS_JSON}")


if __name__ == "__main__":
    main()
