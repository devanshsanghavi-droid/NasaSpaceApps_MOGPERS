"""geo module: county_static.parquet (soil available water storage, NCCPI, irrigated + cropland share).

Inputs
  data/raw/sda/aws_<ST>.json, nccpi_<ST>.json   per-survey-area SSURGO aggregates (pipeline/geo_soils_fetch.py)
  data/raw/nass/qs.census2022.txt.gz, qs.census2017.txt.gz   NASS Census of Agriculture bulk files
      (https://www.nass.usda.gov/datasets/), streamed and filtered to data/raw/nass/census_7state_county.tsv
  data/processed/counties.parquet                (pipeline/geo_counties.py)

Run: /home/user/venv-db/bin/python pipeline/geo_static.py [--refresh]
Output: data/processed/county_static.parquet, key fips (all 667 counties in counties.parquet). See notes/geo.md.
"""
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_N = ROOT / "data" / "raw" / "nass"
RAW_S = ROOT / "data" / "raw" / "sda"
PROC = ROOT / "data" / "processed"
CACHE = RAW_N / "census_7state_county.tsv"
UA = {"User-Agent": "drought-bill-hackathon"}
ST2FIPS = {"IA": "19", "NE": "31", "KS": "20", "MO": "29", "IL": "17", "SD": "46", "MN": "27"}
ACRES_PER_KM2 = 247.105381

CENSUS_ITEMS = {
    "AG LAND, CROPLAND, HARVESTED - ACRES": "harv_cropland_ac",
    "AG LAND, CROPLAND, HARVESTED, IRRIGATED - ACRES": "harv_cropland_irr_ac",
    "AG LAND, IRRIGATED - ACRES": "ag_land_irr_ac",
    "AG LAND, CROPLAND - ACRES": "cropland_ac",
    "CORN, GRAIN - ACRES HARVESTED": "corn_grain_harv_ac",
    "CORN, GRAIN, IRRIGATED - ACRES HARVESTED": "corn_grain_harv_irr_ac",
    "SOYBEANS - ACRES HARVESTED": "soy_harv_ac",
    "SOYBEANS, IRRIGATED - ACRES HARVESTED": "soy_harv_irr_ac",
}

# Survey areas (legend.areasymbol) that are not one-to-one with a county. fips -> list of areasymbols whose
# muacres-weighted aggregate is assigned to that county. Verified against SDA legend.areaname on 2026-11-14.
SDA_SPECIAL = {
    "27071": ["MN625"],                                      # Koochiching County Area
    "27137": ["MN613", "MN615", "MN617", "MN619", "MN621"],  # St. Louis County, five parts
    "29510": ["MO189"],                                      # St. Louis city is mapped inside the St. Louis County survey
    "46015": ["SD603"], "46017": ["SD603"],                  # Brule and Buffalo Counties (one survey)
    "46061": ["SD602"], "46067": ["SD602"],                  # Hanson and Hutchinson Counties (one survey)
    "46033": ["SD606", "SD607"], "46103": ["SD606", "SD607"],  # Custer and Pennington Counties Area (prairie + Black Hills)
    "46071": ["SD610", "SD611"],                             # Jackson County Area, southern + northern parts
    "46093": ["SD600", "SD601"],                             # Meade County, southern + northern parts
    "46102": ["SD613"],                                      # Oglala Lakota County Area
}
SDA_EXCLUDED = {"MN627": "Voyageurs National Park (spans St. Louis + Koochiching)",
                "SD612": "Badlands National Park (spans Jackson, Pennington, Oglala Lakota)"}


def open_lines(path):
    if shutil.which("zcat"):
        p = subprocess.Popen(["zcat", str(path)], stdout=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", bufsize=1 << 20)
        return p.stdout
    return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")


def census_rows():
    if CACHE.exists() and "--refresh" not in sys.argv:
        return pd.read_csv(CACHE, sep="\t", dtype=str, keep_default_na=False)
    out = []
    for yr in ("2022", "2017"):
        path = RAW_N / f"qs.census{yr}.txt.gz"
        if not path.exists():
            url = f"https://www.nass.usda.gov/sites/default/files/datasets/qs.census{yr}.txt.gz"
            print("downloading", url, flush=True)
            with requests.get(url, headers=UA, stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    shutil.copyfileobj(r.raw, f, length=1 << 22)
        lines = open_lines(path)
        header = lines.readline().rstrip("\r\n").split("\t")
        ix = {h: i for i, h in enumerate(header)}
        n = 0
        for line in lines:
            n += 1
            if not line.startswith("CENSUS\t"):
                continue
            f = line.rstrip("\r\n").split("\t")
            if len(f) != len(header):
                continue
            if (f[ix["AGG_LEVEL_DESC"]] == "COUNTY" and f[ix["STATE_ALPHA"]] in ST2FIPS
                    and f[ix["SHORT_DESC"]] in CENSUS_ITEMS and f[ix["DOMAIN_DESC"]] == "TOTAL"):
                out.append(f + [path.name])
        print(path.name, f"{n:,} lines scanned", flush=True)
    df = pd.DataFrame(out, columns=header + ["_SOURCE_FILE"])
    df.to_csv(CACHE, sep="\t", index=False)
    return df


def census_table():
    r = census_rows()
    r = r[r.COUNTY_ANSI.str.strip() != ""].copy()
    r["fips"] = r.STATE_FIPS_CODE.str.zfill(2) + r.COUNTY_ANSI.str.strip().str.zfill(3)
    r["v"] = pd.to_numeric(r.VALUE.str.replace(",", "", regex=False).str.strip(), errors="coerce")
    # "(D)" = withheld to avoid disclosing individual operations; "(Z)" = less than half the unit -> treat as 0
    r.loc[r.VALUE.str.strip() == "(Z)", "v"] = 0.0
    r["col"] = r.SHORT_DESC.map(CENSUS_ITEMS) + "_" + r.YEAR
    w = r.pivot_table(index="fips", columns="col", values="v", aggfunc="first")
    flags = r[r.v.isna()].pivot_table(index="fips", columns="col", values="VALUE", aggfunc="first")
    return w, flags


def sda_table():
    a, n = [], []
    for st in ST2FIPS:
        a += json.loads((RAW_S / f"aws_{st}.json").read_text())["rows"]
        f = RAW_S / f"nccpi_{st}.json"
        if f.exists():
            n += json.loads(f.read_text())["rows"]
    a = pd.DataFrame(a)
    if n:
        a = a.merge(pd.DataFrame(n), on="areasymbol", how="left")
    for c in a.columns:
        if c not in ("areasymbol", "areaname"):
            a[c] = pd.to_numeric(a[c], errors="coerce")
    return a.set_index("areasymbol")


def main():
    cty = pd.read_parquet(PROC / "counties.parquet")
    sda = sda_table()
    fips2st = {v: k for k, v in ST2FIPS.items()}

    recs = []
    for f in cty.fips:
        syms = SDA_SPECIAL.get(f, [fips2st[f[:2]] + f[2:]])
        syms = [s for s in syms if s in sda.index]
        rec = {"fips": f}
        if not syms:
            recs.append(rec)
            continue
        g = sda.loc[syms]
        rec["sda_areasymbols"] = ",".join(syms)
        if f not in SDA_SPECIAL:
            rec["sda_match"] = "one_to_one"
        elif any(k != f and set(v) & set(syms) for k, v in SDA_SPECIAL.items()):
            rec["sda_match"] = "combined_survey_shared_value"  # value is the multi-county survey's average
        elif len(syms) > 1:
            rec["sda_match"] = "county_split_into_parts"
        else:
            rec["sda_match"] = "single_survey_other_symbol"
        rec["sda_area_ac"] = g.areaacres.sum()
        rec["aws0_100_mm"] = 10.0 * g.aws100_x_acres.sum() / g.acres_aws100.sum()
        rec["aws0_150_mm"] = 10.0 * g.aws150_x_acres.sum() / g.acres_aws150.sum()
        rec["aws_rated_frac"] = g.acres_aws100.sum() / g.mu_acres.sum()
        if "nccpi_x_acres" in g:
            rec["nccpi"] = g.nccpi_x_acres.sum() / g.acres_nccpi.sum() if g.acres_nccpi.sum() > 0 else np.nan
            rec["nccpi_rated_frac"] = g.acres_nccpi.sum() / g.mu_acres.sum()
        recs.append(rec)
    soil = pd.DataFrame(recs)
    # survey-area size vs county land+water area as a sanity check (Great Lakes water is outside survey areas)
    tot_ac = (cty.set_index("fips").land_km2 + cty.set_index("fips").water_km2) * ACRES_PER_KM2
    soil["sda_area_to_county_ratio"] = soil.sda_area_ac / soil.fips.map(tot_ac)

    w, flags = census_table()
    out = cty[["fips", "state_abbr", "name", "land_km2"]].merge(soil, on="fips", how="left")
    out = out.merge(w, left_on="fips", right_index=True, how="left")
    for yr in ("2022", "2017"):
        out[f"irrigated_share_{yr}"] = out[f"harv_cropland_irr_ac_{yr}"] / out[f"harv_cropland_ac_{yr}"]
        out[f"corn_irrigated_share_{yr}"] = out[f"corn_grain_harv_irr_ac_{yr}"] / out[f"corn_grain_harv_ac_{yr}"]
        out[f"soy_irrigated_share_{yr}"] = out[f"soy_harv_irr_ac_{yr}"] / out[f"soy_harv_ac_{yr}"]
        out[f"cropland_share_{yr}"] = out[f"cropland_ac_{yr}"] / (out.land_km2 * ACRES_PER_KM2)
    # headline irrigated_share, tiered (first available wins):
    #  1 Census 2022 irrigated harvested cropland / harvested cropland
    #  2 Census 2017 same ratio (2022 withheld "(D)")
    #  3 Census 2022 all irrigated land in farms / harvested cropland, capped at 1 (proxy: also counts irrigated
    #    pasture; used only where the harvested-cropland irrigated item is withheld in both censuses)
    #  4 Census 2017 same proxy
    for yr in ("2022", "2017"):
        out[f"irrigated_share_proxy_{yr}"] = (out[f"ag_land_irr_ac_{yr}"] / out[f"harv_cropland_ac_{yr}"]).clip(upper=1)
    tiers = [("irrigated_share_2022", "2022", "harvested_cropland_irrigated_2022"),
             ("irrigated_share_2017", "2017", "harvested_cropland_irrigated_2017"),
             ("irrigated_share_proxy_2022", "2022", "proxy_ag_land_irrigated_2022"),
             ("irrigated_share_proxy_2017", "2017", "proxy_ag_land_irrigated_2017")]
    out["irrigated_share"] = np.nan
    out["irrigated_share_year"] = None
    out["irrigated_share_method"] = None
    for col, yr, meth in tiers:
        m = out.irrigated_share.isna() & out[col].notna()
        out.loc[m, "irrigated_share"] = out.loc[m, col]
        out.loc[m, "irrigated_share_year"] = yr
        out.loc[m, "irrigated_share_method"] = meth
    out["cropland_share"] = out.cropland_share_2022.fillna(out.cropland_share_2017)
    out["cropland_share_year"] = np.where(out.cropland_share_2022.notna(), "2022",
                                          np.where(out.cropland_share_2017.notna(), "2017", None))
    # record the census disclosure flags (e.g. "(D)") for the two items that drive irrigated_share
    for col in ("harv_cropland_irr_ac_2022", "harv_cropland_irr_ac_2017"):
        out[f"flag_{col}"] = out.fips.map(flags[col]) if col in flags else None
    out = out.drop(columns=["land_km2"])
    for c in out.columns:
        if pd.api.types.is_float_dtype(out[c]) and not c.endswith("_ac_2022") and not c.endswith("_ac_2017"):
            out[c] = out[c].astype(float).round(4)
    out.to_parquet(PROC / "county_static.parquet", index=False)

    print("county_static:", len(out), "rows,", out.shape[1], "cols")
    print(out[["aws0_100_mm", "aws0_150_mm", "nccpi", "irrigated_share", "cropland_share"]].describe().round(3))
    print("null counts:", out[["aws0_100_mm", "nccpi", "irrigated_share", "cropland_share"]].isna().sum().to_dict())
    print("irrigated_share_method:", out.irrigated_share_method.value_counts(dropna=False).to_dict())
    print(out.groupby("state_abbr")[["aws0_100_mm", "irrigated_share", "nccpi"]].mean().round(3))
    odd = out[(out.sda_area_to_county_ratio < 0.95) | (out.sda_area_to_county_ratio > 1.05)]
    print("survey area / county area outside 0.95-1.05:\n",
          odd[["fips", "name", "state_abbr", "sda_areasymbols", "sda_area_to_county_ratio"]].to_string())
    print(out[out.fips == "19149"].T.to_string())


if __name__ == "__main__":
    main()
