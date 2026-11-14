"""County crop-rotation diversity from the CDL lattice samples (2008-2024).

Inputs: data/raw/cdl/lattice_<year>.npy (uint8 CDL codes on the fixed 240 m lattice, see cdl_common.py).
Outputs: data/processed/cdl_county_year.parquet (fips x window-end year 2012-2024) and
         data/processed/cdl_county_static.parquet (fips, whole record 2008-2024).

Usage: python pipeline/cdl_metrics.py
"""
import os, sys, time
import numpy as np
import pandas as pd
import rasterio.features
from rasterio.transform import from_origin

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdl_common import (PROC, RAW, YEARS, X0, YTOP, NX, NY, SPACING, lattice_path, load_counties)  # noqa: E402

# ---- crop class grouping -------------------------------------------------------------------------------------
# internal class ids
X, C, S, W, O, A, G, P, R, F = range(10)
CLASS_NAMES = ["X", "C", "S", "W", "O", "A", "G", "P", "R", "F"]
LETTER = np.array(list("XCSWOAGPXX"))   # contract letters: R (other crop) and F (fallow) are written as X
CROPLAND = np.array([c in (C, S, W, O, A, G, R, F) for c in range(10)])  # counts toward "cropland pixel"
DIVERSITY = [C, S, W, O, A, G, P, R]                                        # classes counted in diversity metrics

GROUPS = {
    C: [1, 12, 13, 241],                                   # corn, sweet corn, pop/orn corn, dbl corn/soy
    S: [5, 239, 240],                                      # soybeans, dbl soy/cotton, dbl soy/oats
    W: [22, 23, 24, 26, 225, 236, 238],                    # durum, spring, winter wheat; dbl crops led by wheat
    O: [21, 25, 27, 28, 30, 205, 226, 235, 237, 254],      # barley, other small grains, rye, oats, speltz,
                                                           # triticale; dbl crops led by oats/barley
    A: [36, 37, 58],                                       # alfalfa, other hay/non-alfalfa, clover/wildflowers
    G: [4],                                                # sorghum
    P: [59, 60, 62, 171, 176, 181],                        # sod/grass seed, switchgrass, pasture/grass,
                                                           # grassland herbaceous, grassland/pasture, pasture/hay
    F: [61],                                               # fallow/idle cropland
}


def build_lut():
    lut = np.zeros(256, np.uint8)   # default X: background, developed, water, forest, wetland, barren, ...
    crop_codes = set(range(1, 61)) | set(range(66, 81)) | set(range(200, 256))
    for c in crop_codes:
        lut[c] = R                   # any other agricultural CDL class (sunflower, canola, dry beans, sugarbeets...)
    for k, codes in GROUPS.items():
        for c in codes:
            lut[c] = k
    return lut


LUT = build_lut()


def shannon(counts):
    """counts: (K, N) per-class counts. Natural-log Shannon entropy per column; NaN where total = 0."""
    tot = counts.sum(0).astype(np.float32)
    with np.errstate(divide="ignore", invalid="ignore"):
        p = counts / tot
        h = -np.nansum(np.where(p > 0, p * np.log(p), 0.0), axis=0)
    h[tot == 0] = np.nan
    return h.astype(np.float32)


def window_metrics(cls):
    """cls: (T, N) class ids for a window of T years. Returns dict of per-pixel arrays (N,)."""
    T = cls.shape[0]
    counts = np.stack([(cls == k).sum(0) for k in DIVERSITY]).astype(np.int16)   # (8, N)
    present = counts > 0
    ncrop = present.sum(0).astype(np.int8)
    isc = cls == C
    cc3 = np.zeros(cls.shape[1], bool)
    for t in range(T - 2):
        cc3 |= isc[t] & isc[t + 1] & isc[t + 2]
    iC, iS = DIVERSITY.index(C), DIVERSITY.index(S)
    cs_only = present[iC] & present[iS] & (ncrop == 2)
    sg = ((cls == W) | (cls == O)).any(0)
    per = ((cls == A) | (cls == P)).any(0)
    return dict(div=shannon(counts), ncrop=ncrop, cc3=cc3, cs_only=cs_only, three=ncrop >= 3, sg=sg, per=per)


ROT_CLASSES = ["with perennial", "continuous corn", "corn-soy", "3+ crop", "other"]
ROT_COLS = ["rc_with_perennial", "rc_continuous_corn", "rc_corn_soy", "rc_3plus", "rc_other"]


def rotation_class_codes(m):
    """Per-pixel rotation class index into ROT_CLASSES from window_metrics() output, first rule that applies:
    any alfalfa/hay/grass year -> with perennial; corn >= 3 consecutive years -> continuous corn;
    only corn+soy (both present) -> corn-soy; >= 3 distinct crop classes -> 3+ crop; else other."""
    rc = np.full(m["per"].shape, 4, np.int8)
    rc[m["three"]] = 3
    rc[m["cs_only"]] = 2
    rc[m["cc3"]] = 1
    rc[m["per"]] = 0
    return rc


def county_index_raster(g):
    shapes = [(geom, i + 1) for i, geom in enumerate(g.to_crs(5070).geometry)]
    tr = from_origin(X0 - SPACING / 2, YTOP + SPACING / 2, SPACING, SPACING)  # cell centres = lattice points
    return rasterio.features.rasterize(shapes, out_shape=(NY, NX), transform=tr, fill=0, dtype="int16")


def main():
    t0 = time.time()
    missing = [y for y in YEARS if not os.path.exists(lattice_path(y))]
    if missing:
        sys.exit(f"missing lattice years {missing}: run cdl_pc_fetch.py / cdl_nass_fetch.py first")
    g = load_counties()
    cidx = county_index_raster(g)
    sel = cidx > 0
    county = cidx[sel] - 1                                   # (N,) county row in g
    nc = len(g)
    n_pts = np.bincount(county, minlength=nc)
    print(f"{sel.sum():,} lattice points inside {nc} counties", flush=True)
    cls = np.empty((len(YEARS), sel.sum()), np.uint8)
    for i, y in enumerate(YEARS):
        lat = np.load(lattice_path(y))
        v = lat[sel]
        if (v == 0).mean() > 0.001:
            print(f"  WARNING {y}: {(v == 0).mean():.4f} of in-county points have CDL code 0 (no data)")
        cls[i] = LUT[v]
    del lat, v
    crop = CROPLAND[cls]                                     # (T, N) bool
    ncrop_years = crop.sum(0)

    def agg(mask, metrics, extra_shares):
        """Mean of per-pixel metrics over pixels in `mask`, by county."""
        cnt = np.bincount(county[mask], minlength=nc).astype(float)
        out = {"n_px": cnt.astype(int)}
        with np.errstate(invalid="ignore", divide="ignore"):
            for k, v in metrics.items():
                v = v[mask].astype(float)
                ok = ~np.isnan(v)
                s = np.bincount(county[mask][ok], weights=v[ok], minlength=nc)
                n = np.bincount(county[mask][ok], minlength=nc)
                out[k] = s / n
            for k, v in extra_shares.items():
                out[k] = np.bincount(county[mask], weights=v[mask].astype(float), minlength=nc) / cnt
        return out

    names = dict(div="div_shannon_5y", ncrop="n_crops_5y", cc3="share_cont_corn", cs_only="share_cs_only",
                 three="share_3plus", sg="share_small_grain_5y", per="share_perennial_5y")
    rows = []
    for ye in range(YEARS[0] + 4, YEARS[-1] + 1):            # 2012..2024
        i1 = YEARS.index(ye) + 1
        w = cls[i1 - 5:i1]
        mask = crop[i1 - 5:i1].sum(0) >= 3                   # cropland in >= 3 of the 5 window years
        m = window_metrics(w)
        cy = cls[i1 - 1]
        shares = dict(corn_share=cy == C, soy_share=cy == S, wheat_share=cy == W, sorghum_share=cy == G,
                      hay_alfalfa_share=cy == A)
        rc = rotation_class_codes(m)
        for j, col in enumerate(ROT_COLS):
            shares[col] = rc == j
        a = agg(mask, m, shares)
        df = pd.DataFrame({"fips": g.fips.values, "year": ye, "n_px": a["n_px"]})
        for k, v in names.items():
            df[v] = a[k]
        for k in shares:
            df[k] = a[k]
        crop_cols = ["corn_share", "soy_share", "wheat_share", "sorghum_share", "hay_alfalfa_share"]
        df["other_share"] = 1 - df[crop_cols].sum(1)
        df = df[[c for c in df.columns if c not in ROT_COLS] + ROT_COLS]
        rows.append(df)
        print(f"  window {ye - 4}-{ye}: {mask.sum():,} cropland px", flush=True)
    cy = pd.concat(rows, ignore_index=True)

    # whole record 2008-2024
    mask = ncrop_years >= 9                                  # cropland in >= 9 of 17 years
    m = window_metrics(cls)
    shares = dict(corn_share=(cls == C).mean(0), soy_share=(cls == S).mean(0), wheat_share=(cls == W).mean(0),
                  sorghum_share=(cls == G).mean(0), hay_alfalfa_share=(cls == A).mean(0))
    a = agg(mask, m, shares)
    st = pd.DataFrame({"fips": g.fips.values, "n_px": a["n_px"]})
    for k, v in names.items():
        st[v] = a[k]   # same column names as cdl_county_year, but computed over the 17-year record
    for k in shares:
        st[k] = a[k]
    st["other_share"] = 1 - st[list(shares)].sum(1)
    st["n_pts"] = n_pts
    st["cropland_frac"] = st.n_px / st.n_pts
    st["years"] = f"{YEARS[0]}-{YEARS[-1]}"

    # too few cropland samples -> metrics are not meaningful
    MIN_PX = 20
    for df in (cy, st):
        bad = df.n_px < MIN_PX
        cols = [c for c in df.columns if c not in ("fips", "year", "n_px", "n_pts", "cropland_frac", "years")]
        df.loc[bad, cols] = np.nan
        print(f"  {bad.sum()} rows with n_px < {MIN_PX} set to NaN")
    cy["n_px"] = cy.n_px.astype("int32"); cy["year"] = cy.year.astype("int16")
    st["n_px"] = st.n_px.astype("int32"); st["n_pts"] = st.n_pts.astype("int32")
    for c in cy.columns:
        if cy[c].dtype == float:
            cy[c] = cy[c].astype("float32")
    for c in st.columns:
        if st[c].dtype == float:
            st[c] = st[c].astype("float32")
    os.makedirs(PROC, exist_ok=True)
    cy.sort_values(["fips", "year"]).to_parquet(os.path.join(PROC, "cdl_county_year.parquet"), index=False)
    st.sort_values("fips").to_parquet(os.path.join(PROC, "cdl_county_static.parquet"), index=False)
    print(f"wrote cdl_county_year ({len(cy)} rows) and cdl_county_static ({len(st)} rows) in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
