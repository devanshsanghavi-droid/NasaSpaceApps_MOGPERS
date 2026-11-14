"""Build WIMAS processed tables from the raw per-county downloads (see pumping_fetch.py).

Outputs (data/processed/):
  wimas_use.parquet          one row per point of diversion (PD) x year x use (IRR / MUN), 1990-2025 as reported
  wimas_county_year.parquet  one row per county x year (irrigation totals, AF/acre, by-crop AF/acre, municipal AF)
  wimas_summary.json         coverage + sanity-check numbers (GMD totals, AF/acre medians)

Aggregation conventions (checked against the WIMAS web tool itself, see notes/pumping.md):
  * Reported use: WIMAS stores one water-use record per water right x PD x year (af_used already allocated to that
    right/PD). The WIMAS "Water Use Trends" page total for a selection equals the plain sum of af_used / acres_irr
    over these records (Greeley IRR groundwater 1990: page 43,531.16 AF vs our sum 43,531.14 AF), so we sum the same way.
  * Authorized quantity: WIMAS county totals equal the sum of add_quant (additional, non-overlapping AF) over unique
    (wr_id, quant_id). Quantities stored by PD (qstor_ind=2) are assigned to that PD; quantities stored by water right
    (qstor_ind=1) are split evenly over that right's PDs. Per-PD authorized_af is therefore an allocation; county sums
    are exact.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "wimas"
OUT = APP / "data" / "processed"
OUT.mkdir(parents=True, exist_ok=True)

from pumping_fetch import COUNTIES  # noqa: E402  (same directory)

CODE2FIPS = {code: f"20{c3:03d}" for c3, (name, code, gmd) in COUNTIES.items()}
FIPS2GMD = {f"20{c3:03d}": gmd for c3, (name, code, gmd) in COUNTIES.items()}
FIPS2NAME = {f"20{c3:03d}": name for c3, (name, code, gmd) in COUNTIES.items()}

# WIMAS crop codes, KGS OFR 2005-30 (WIMAS v5 user manual), "Crop Codes" table
CROP_NAMES = {
    1: "Alfalfa", 2: "Corn", 3: "Grain Sorghum", 4: "Soybeans", 5: "Wheat", 6: "Oats", 7: "Barley", 8: "Rye",
    9: "Dry Beans", 10: "Sunflowers", 11: "Golf Course", 12: "Truck Farm", 13: "Orchard", 14: "Nursery", 15: "Other",
    16: "More than one type of crop", 17: "Double Crop", 18: "Alfalfa & Corn", 19: "Alfalfa & Grain Sorghum",
    20: "Alfalfa & Soybeans", 21: "Alfalfa & Wheat", 22: "Alfalfa & other", 23: "Corn & Grain Sorghum",
    24: "Corn & Soybeans", 25: "Corn & Wheat", 26: "Corn & Other", 27: "Grain Sorghum & Soybeans",
    28: "Grain Sorghum & Wheat", 29: "Grain Sorghum & Other", 30: "Soybeans & Wheat", 31: "Soybeans & Other",
    32: "Wheat & Other", 33: "Alfalfa, Corn & Grain Sorghum", 34: "Alfalfa, Corn & Soybeans", 35: "Alfalfa, Corn & Wheat",
    36: "Alfalfa, Corn & Other", 37: "Alfalfa, Grain Sorghum & Soybeans", 38: "Alfalfa, Grain Sorghum & Wheat",
    39: "Alfalfa, Grain Sorghum & Other", 40: "Alfalfa, Soybeans & Wheat", 41: "Alfalfa, Soybeans & Other",
    42: "Alfalfa, Wheat & Other", 43: "Corn, Grain Sorghum & Soybeans", 44: "Corn, Grain Sorghum & Wheat",
    45: "Corn, Grain Sorghum & Other", 46: "Corn, Soybeans & Wheat", 47: "Corn, Soybeans & Other",
    48: "Corn, Wheat & Other", 49: "Grain Sorghum, Soybeans & Wheat", 50: "Grain Sorghum, Soybeans & Other",
    51: "Grain Sorghum, Wheat & Other", 52: "Soybeans, Wheat & Other", 53: "Alfalfa, Corn, Grain Sorghum & Soybeans",
    54: "Alfalfa, Corn, Grain Sorghum & Wheat", 55: "Alfalfa, Corn, Grain Sorghum & Other",
    56: "Alfalfa, Corn, Soybeans & Wheat", 57: "Alfalfa, Corn, Soybeans & Other", 58: "Alfalfa, Corn, Wheat & Other",
    59: "Alfalfa, Grain Sorghum, Soybeans & Wheat", 60: "Alfalfa, Grain Sorghum, Soybeans & Other",
    61: "Alfalfa, Grain Sorghum, Wheat & Other", 62: "Alfalfa, Soybeans, Wheat & Other",
    63: "Corn, Grain Sorghum, Soybeans & Wheat", 64: "Corn, Grain Sorghum, Soybeans & Other",
    65: "Corn, Grain Sorghum, Wheat & Other", 66: "Corn, Soybeans, Wheat & Other",
    67: "Grain Sorghum, Soybeans, Wheat & Other", 68: "Alfalfa, Corn, Grain Sorghum, Soybeans",
    69: "Alfalfa, Corn, Grain Sorghum, Wheat", 70: "Alfalfa, Corn, Grain Sorghum Wheat & Other",
    71: "Alfalfa, Corn, Soybeans, Wheat & Other", 72: "Alfalfa, Grain Sorghum, Soybeans, Wheat & Other",
    73: "Corn, Grain Sorghum, Soybeans, Wheat & Other", 74: "Alfalfa, Corn, Grain Sorghum, Soybeans, Wheat & Other",
    75: "Pasture", 76: "Sod/Turf Grass", 77: "Cotton", 78: "Grapes",
}
# single-crop groups used for by-crop AF/acre
CROP_GROUP = {1: "alfalfa", 2: "corn", 3: "sorghum", 4: "soybeans", 5: "wheat", 77: "cotton", 75: "pasture"}
SYSTEM_NAMES = {1: "Flood", 2: "Trickle-drip", 3: "Center pivot", 4: "Center pivot LEPA",
                5: "Sprinkler other than center pivot", 6: "Center pivot and flood", 7: "SDI in combination",
                8: "Other", 9: "Center pivot with mobile drip"}


def read_raw(kind: str) -> pd.DataFrame:
    frames = []
    for p in sorted(RAW.glob(f"20???_{kind}.txt")):
        d = pd.read_csv(p, skipinitialspace=True, dtype=str, keep_default_na=False)
        d.columns = [c.strip() for c in d.columns]
        d = d.apply(lambda s: s.str.strip())
        d["file_fips"] = p.name[:5]
        frames.append(d)
    return pd.concat(frames, ignore_index=True)


def num(s):
    return pd.to_numeric(s.replace("", np.nan), errors="coerce")


def wr_file_no(d):
    q = d["wr_qual"] if "wr_qual" in d else d["wr_qualifier"]
    vc = d["vcnty_code"] if "vcnty_code" in d else d["vested_county_code"]
    return (d["right_type"] + " " + vc.where(vc != "", "") + " " + d["wr_num"] + " " + q).str.replace(r"\s+", " ", regex=True).str.strip()


def main():
    wu = read_raw("wuse")
    qt = read_raw("qty")
    mn = read_raw("main")
    print("raw rows: wuse", len(wu), "qty", len(qt), "main", len(mn))
    # rights selected by use filter IRR/MUN; a PD can appear in two county files only if counties overlap -> dedupe
    wu = wu.drop_duplicates(subset=[c for c in wu.columns if c != "file_fips"])
    # The WIMAS wuse export repeats a water-use record once per aquifer code and per special-use-area code of the PD
    # (join artifact: e.g. Finney 14,006 of 84,662 rows sit in such repeated groups, Kearny 18,334 of 42,166). Collapse these so each
    # right x PD x year x report is counted once; keep the codes as ';'-joined lists.
    art = ["aquifer", "sua", "fo_num"]
    key = [c for c in wu.columns if c not in art + ["file_fips"]]
    n0 = len(wu)
    codes = wu.groupby(key, sort=False)[["aquifer", "sua"]].agg(lambda s: ";".join(sorted(set(x for x in s if x))))
    wu = wu.drop_duplicates(subset=key).drop(columns=["aquifer", "sua"]).merge(codes.reset_index(), on=key, how="left")
    print(f"collapsed aquifer/SUA join duplicates: {n0} -> {len(wu)} rows")
    for c in ["af_used", "acres_irr", "longitude", "latitude", "mtr_qty", "hours_pump", "pump_rate", "dpth_water"]:
        wu[c] = num(wu[c])
    wu["year"] = num(wu["wua_year"]).astype("Int64")
    wu["crop"] = num(wu["crop_code"]).astype("Int64")
    wu.loc[wu["crop"] == 0, "crop"] = pd.NA
    wu["system"] = num(wu["type_system"]).astype("Int64")
    wu["county_fips"] = wu["county"].map(CODE2FIPS).fillna(wu["file_fips"])
    wu["wr_file_no"] = wr_file_no(wu)
    wu["use"] = wu["umw_code"]
    wu = wu[wu["use"].isin(["IRR", "MUN"])].copy()

    # ---------- authorized quantity per PD ----------
    for c in ["auth_quant", "add_quant"]:
        qt[c] = num(qt[c])
    qt = qt[qt["quant_unit"].eq("AF")].drop_duplicates(["wr_id", "quant_id", "pdiv_id", "umw_code"])
    npd = qt.groupby(["wr_id", "quant_id"])["pdiv_id"].transform("nunique")
    qt["alloc_af"] = np.where(qt["qstor_ind"].eq("2"), qt["add_quant"], qt["add_quant"] / npd)
    # a (wr_id, quant_id) stored by PD appears once per PD with its own value; if repeated per PD under qstor 1 we split
    auth = qt.groupby(["pdiv_id", "umw_code"]).agg(authorized_af=("alloc_af", "sum")).reset_index()
    auth_county = (qt.assign(county_fips=qt["county"].map(CODE2FIPS))
                   .drop_duplicates(["wr_id", "quant_id", "umw_code"])
                   .groupby(["county_fips", "umw_code"])["add_quant"].sum().unstack(fill_value=0))

    # ---------- per PD x year x use ----------
    wu["af_pos"] = wu["af_used"].clip(lower=0)
    wu["has_crop"] = wu["crop"].notna()

    def first_valid(s):
        s = s.dropna()
        return s.iloc[0] if len(s) else pd.NA

    g = wu.sort_values(["acres_irr"], ascending=False).groupby(["pdiv_id", "year", "use"], sort=False)
    pd_year = g.agg(
        wr_file_no=("wr_file_no", lambda s: ";".join(sorted(set(s)))),
        n_rights=("wr_id", "nunique"),
        lon=("longitude", "first"), lat=("latitude", "first"),
        county_fips=("county_fips", "first"), gmd_wimas=("gmd", "first"),
        source=("source", lambda s: "".join(sorted(set(s)))),
        aquifer_codes=("aquifer", "first"),
        af_reported=("af_used", lambda s: s.sum(min_count=1)),
        acres_irrigated=("acres_irr", lambda s: s.sum(min_count=1)),
        crop_code=("crop", first_valid),
        system_code=("system", first_valid),
        wur_code=("wur_code", lambda s: ";".join(sorted(set(x for x in s if x)))),
        metered=("meter_unit", lambda s: bool((s != "").any())),
        depth_to_water_ft=("dpth_water", "max"),
        twp=("twp", "first"), twp_dir=("twp_dir", "first"), rng=("rng", "first"), rng_dir=("rng_dir", "first"),
        sect=("sect", "first"),
        qual=("qual1", "first"),
    ).reset_index()
    # PLSS quarter call (qual4..qual1 = smallest..largest tract) from first record
    q = wu.groupby("pdiv_id")[["qual4", "qual3", "qual2", "qual1"]].first()
    pd_year["plss_qq"] = pd_year["pdiv_id"].map((q["qual4"] + " " + q["qual3"] + " " + q["qual2"] + " " + q["qual1"])
                                                 .str.replace(r"\s+", " ", regex=True).str.strip())
    pd_year = pd_year.drop(columns=["qual"])
    pd_year["crop_name"] = pd_year["crop_code"].map(lambda c: CROP_NAMES.get(int(c)) if pd.notna(c) else None)
    pd_year["crop_group"] = pd_year["crop_code"].map(
        lambda c: CROP_GROUP.get(int(c), "multiple/other") if pd.notna(c) else None)
    pd_year["system_name"] = pd_year["system_code"].map(lambda c: SYSTEM_NAMES.get(int(c)) if pd.notna(c) else None)
    pd_year = pd_year.merge(auth.rename(columns={"umw_code": "use"}), on=["pdiv_id", "use"], how="left")
    pd_year["gmd"] = pd_year["gmd_wimas"].replace("", np.nan)
    pd_year["gmd"] = pd.to_numeric(pd_year["gmd"], errors="coerce").astype("Int64")
    pd_year["gmd_county"] = pd_year["county_fips"].map(FIPS2GMD).astype("Int64")
    pd_year = pd_year.drop(columns=["gmd_wimas"])
    pd_year["pdiv_id"] = pd_year["pdiv_id"].astype("int64")
    for c in ["twp", "rng", "sect"]:
        pd_year[c] = pd.to_numeric(pd_year[c], errors="coerce").astype("Int64")
    pd_year["crop_code"] = pd_year["crop_code"].astype("Int64")
    pd_year["system_code"] = pd_year["system_code"].astype("Int64")
    pd_year["year"] = pd_year["year"].astype("int64")
    ap = pd_year["af_reported"] / pd_year["acres_irrigated"]
    pd_year["af_per_acre"] = ap.where((pd_year["acres_irrigated"] > 0) & (pd_year["af_reported"] > 0))
    # flag implausible application depths (> 5 ft/ac or < 0.05 ft/ac) - kept but flagged
    pd_year["flag_af_per_acre"] = pd_year["af_per_acre"].notna() & ~pd_year["af_per_acre"].between(0.05, 5.0)
    pd_year = pd_year.sort_values(["county_fips", "pdiv_id", "year", "use"]).reset_index(drop=True)
    cols = ["pdiv_id", "year", "use", "wr_file_no", "n_rights", "lon", "lat", "county_fips", "gmd", "gmd_county",
            "source", "aquifer_codes", "af_reported", "acres_irrigated", "af_per_acre", "flag_af_per_acre", "crop_code", "crop_name",
            "crop_group", "system_code", "system_name", "authorized_af", "wur_code", "metered", "depth_to_water_ft",
            "sect", "twp", "twp_dir", "rng", "rng_dir", "plss_qq"]
    pd_year = pd_year[cols]
    for c in ["af_reported", "acres_irrigated", "af_per_acre", "authorized_af", "depth_to_water_ft"]:
        pd_year[c] = pd_year[c].astype("float32")  # keeps file < ~5 MB; values are reported to 0.01 AF at most
    pd_year.to_parquet(OUT / "wimas_use.parquet", index=False, compression="zstd", compression_level=19)
    print("wimas_use rows", len(pd_year), "PDs", pd_year.pdiv_id.nunique())

    # ---------- county x year ----------
    irr = pd_year[pd_year["use"] == "IRR"]
    both = irr[(irr.af_reported > 0) & (irr.acres_irrigated > 0) & ~irr.flag_af_per_acre]
    cy = irr.groupby(["county_fips", "year"]).agg(
        irr_af=("af_reported", "sum"), irr_acres=("acres_irrigated", "sum"),
        n_pdiv=("af_reported", lambda s: int((s > 0).sum())),
        n_pdiv_reports=("af_reported", "size"),
    )
    gw = irr[irr.source.str.contains("G")].groupby(["county_fips", "year"])["af_reported"].sum().rename("irr_af_gw")
    sw = irr[irr.source == "S"].groupby(["county_fips", "year"])["af_reported"].sum().rename("irr_af_sw")
    mm = both.groupby(["county_fips", "year"]).agg(af_m=("af_reported", "sum"), ac_m=("acres_irrigated", "sum"))
    cy = cy.join([gw, sw, mm])
    cy["af_per_acre"] = cy["af_m"] / cy["ac_m"]
    cy = cy.drop(columns=["af_m", "ac_m"])
    # by single-crop group
    for grp in ["corn", "sorghum", "wheat", "soybeans", "alfalfa", "cotton"]:
        b = both[both.crop_group == grp].groupby(["county_fips", "year"]).agg(a=("af_reported", "sum"),
                                                                             c=("acres_irrigated", "sum"))
        cy = cy.join(b.rename(columns={"a": f"af_{grp}", "c": f"acres_{grp}"}))
        cy[f"af_per_acre_{grp}"] = cy[f"af_{grp}"] / cy[f"acres_{grp}"]
        cy = cy.drop(columns=[f"af_{grp}"])
    cy["acres_crop_reported"] = irr[irr.crop_code.notna()].groupby(["county_fips", "year"])["acres_irrigated"].sum()
    mun = pd_year[pd_year.use == "MUN"].groupby(["county_fips", "year"])["af_reported"].sum().rename("mun_af")
    cy = cy.join(mun).reset_index()
    cy["county_name"] = cy["county_fips"].map(FIPS2NAME)
    cy["gmd"] = cy["county_fips"].map(FIPS2GMD).astype("Int64")
    cy["irr_authorized_af"] = cy["county_fips"].map(auth_county.get("IRR", pd.Series(dtype=float)))
    for c in [c for c in cy.columns if c.startswith("acres_")] + ["n_pdiv", "n_pdiv_reports"]:
        cy[c] = cy[c].fillna(0) if c.startswith("n_") else cy[c]
    # county-years whose WIMAS query failed server-side (pumping_fetch writes <fips>_wuse_missing.txt): blank them
    cy["complete"] = True
    for mf in RAW.glob("20???_wuse_missing.txt"):
        for line in mf.read_text().splitlines():
            if line.strip():
                yr = int(line.split("\t")[0])
                m = (cy.county_fips == mf.name[:5]) & (cy.year == yr)
                if not m.any():
                    cy = pd.concat([cy, pd.DataFrame({"county_fips": [mf.name[:5]], "year": [yr]})], ignore_index=True)
                    m = (cy.county_fips == mf.name[:5]) & (cy.year == yr)
                num_cols = [c for c in cy.columns if c not in ("county_fips", "year", "county_name", "gmd",
                                                               "irr_authorized_af", "complete")]
                cy.loc[m, num_cols] = np.nan
                cy.loc[m, "complete"] = False
                cy.loc[m, "county_name"] = FIPS2NAME[mf.name[:5]]
                cy.loc[m, "gmd"] = FIPS2GMD[mf.name[:5]]
    cy["complete"] = cy["complete"].astype(bool)
    cy = cy.sort_values(["county_fips", "year"]).reset_index(drop=True)
    cy.to_parquet(OUT / "wimas_county_year.parquet", index=False, compression="zstd")
    print("county_year rows", len(cy))

    # ---------- summary / sanity ----------
    gmd_year = cy.groupby(["gmd", "year"])[["irr_af", "irr_acres"]].sum().reset_index()
    gmd_year["ft_per_acre"] = gmd_year.irr_af / gmd_year.irr_acres
    # GMD totals using WIMAS's own per-PD gmd attribute (official district membership), IRR only
    gw_ = irr[irr.gmd.notna()].groupby(["gmd", "year"])[["af_reported", "acres_irrigated"]].sum().reset_index()
    ts22 = {}
    bad = cy[~cy.complete]
    for gmd_, d in gw_.groupby("gmd"):
        d = d[~d.year.isin(bad[bad.gmd == gmd_].year)]  # drop GMD-years with a county query failure
        s = d.set_index("year")["af_reported"]
        yrs = np.array([y for y in range(1996, 2017) if y in s.index])
        if len(yrs) >= 18:
            b, a = np.polyfit(yrs, s.loc[yrs].values, 1)
            fit0, fit1 = a + b * 1996, a + b * 2016
            ts22[f"GMD{int(gmd_)}"] = {
                "mean_af_1996_2016": round(float(s.loc[yrs].mean())),
                "years_used_1996_2016": len(yrs),
                "linear_trend_change_pct_1996_2016": round(float(100 * (fit1 - fit0) / fit0), 1),
                "mean_af_2005_2018": round(float(s.loc[2005:2018].mean())),
                "mean_af_2019_2024": round(float(s.loc[2019:2024].mean())),
                "mean_ft_per_acre_2000_2024": round(float(d[d.year.between(2000, 2024)].af_reported.sum()
                                                          / d[d.year.between(2000, 2024)].acres_irrigated.sum()), 3),
            }
    summary = {
        "gmd_attr_checks_vs_KGS_TS22": ts22,
        "source": "Kansas WIMAS (KGS / KDA-DWR) via https://geohydro.kgs.ku.edu/geohydro/wimas/ ; data as of WIMAS weekly build 11/08/2026",
        "n_rows_wimas_use": int(len(pd_year)), "n_pdiv": int(pd_year.pdiv_id.nunique()),
        "n_pdiv_irr": int(irr.pdiv_id.nunique()),
        "years": [int(pd_year.year.min()), int(pd_year.year.max())],
        "counties": sorted(cy.county_fips.unique().tolist()),
        "share_pd_years_with_lonlat": float(pd_year.lon.notna().mean()),
        "share_irr_pd_years_with_crop": float(irr.crop_code.notna().mean()),
        "irr_authorized_af_by_county": {k: round(float(v), 1) for k, v in auth_county.get("IRR", pd.Series(dtype=float)).items()},
        "gmd_year": {f"GMD{int(r.gmd)}_{int(r.year)}": {"irr_af": round(r.irr_af), "irr_acres": round(r.irr_acres),
                                                       "ft_per_acre": round(r.ft_per_acre, 3)}
                     for r in gmd_year.itertuples()},
        "region_mean_irr_af_2000_2024": round(float(cy[cy.year.between(2000, 2024)].groupby("year").irr_af.sum().mean())),
        "median_pd_af_per_acre_by_crop_2000_2024": {
            k: round(float(v), 3) for k, v in
            both[both.year.between(2000, 2024)].groupby("crop_group").apply(
                lambda d: d.af_reported.sum() / d.acres_irrigated.sum(), include_groups=False).items()},
    }
    (OUT / "wimas_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "gmd_year"}, indent=1)[:3000])


if __name__ == "__main__":
    main()
