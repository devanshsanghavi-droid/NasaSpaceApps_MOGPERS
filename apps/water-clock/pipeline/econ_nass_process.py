"""econ: turn the filtered NASS QuickStats bulk rows (econ_nass_fetch.py) into nass_county.parquet and prices.parquet.

nass_county.parquet  key (county_fips, year, crop, practice); SURVEY, annual (REFERENCE_PERIOD=YEAR), DOMAIN=TOTAL.
  agg_level: COUNTY (real region counties, county_fips = 20xxx)
             DISTRICT_OTHER (NASS "OTHER (COMBINED) COUNTIES" of a district, county_fips = 20C + ASD code)
             DISTRICT (NASS agricultural district total, county_fips = 20D + ASD code; 10 NW, 40 WC, 70 SW)
             STATE (Kansas, county_fips = 20000)
  crop: corn (grain), sorghum (grain), wheat (winter; falls back to all wheat if no winter row), soybeans, cotton (upland)
  practice: ALL, IRRIGATED, NON-IRRIGATED, plus for wheat NON-IRRIGATED-FALLOW (following summer fallow) and
            NON-IRRIGATED-CONTINUOUS (continuous crop)
  yield (bu/ac; cotton lb/ac), yield_unit, harvested_acres, suppressed flags, cv_pct
prices.parquet  key (year, crop): Kansas marketing-year average price received, 2010-2025.
Run: python3 pipeline/econ_nass_process.py
"""
import re
from pathlib import Path

import numpy as np
import pandas as pd

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "nass" / "ks_crops_rows.tsv"
OUT = APP / "data" / "processed"
Y0, Y1 = 2000, 2025
DISTRICTS = {"10": "NORTHWEST", "40": "WEST CENTRAL", "70": "SOUTHWEST"}

CROP_PREFIX = {  # SHORT_DESC prefix (before practice) -> (crop, priority); lower priority wins
    "CORN, GRAIN": ("corn", 0),
    "SORGHUM, GRAIN": ("sorghum", 0),
    "WHEAT, WINTER": ("wheat", 0),
    "WHEAT": ("wheat", 1),
    "SOYBEANS": ("soybeans", 0),
    "COTTON, UPLAND": ("cotton", 0),
}
PRACTICE = {"": "ALL", "IRRIGATED": "IRRIGATED", "NON-IRRIGATED": "NON-IRRIGATED",
            "NON-IRRIGATED, FOLLOWING SUMMER FALLOW": "NON-IRRIGATED-FALLOW",
            "NON-IRRIGATED, CONTINUOUS CROP": "NON-IRRIGATED-CONTINUOUS"}
STAT_RE = re.compile(r"^(?P<body>.+?) - (?P<stat>YIELD, MEASURED IN (?P<unit>BU|LB) / ACRE|ACRES HARVESTED)$")


def parse_short(s):
    m = STAT_RE.match(s)
    if not m:
        return None
    body = m["body"]
    for pref in sorted(CROP_PREFIX, key=len, reverse=True):
        if body == pref or body.startswith(pref + ", "):
            rest = body[len(pref):].lstrip(", ")
            if rest not in PRACTICE:
                return None
            crop, pri = CROP_PREFIX[pref]
            stat = "yield" if m["stat"].startswith("YIELD") else "harvested_acres"
            unit = (m["unit"].lower() + "/ac") if stat == "yield" else "acres"
            return crop, pri, PRACTICE[rest], stat, unit
    return None


def num(v):
    v = v.replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return np.nan


def yields_areas(raw):
    d = raw[(raw.SOURCE_DESC == "SURVEY") & (raw.REFERENCE_PERIOD_DESC == "YEAR") & (raw.DOMAIN_DESC == "TOTAL")
            & raw.STATISTICCAT_DESC.isin(["YIELD", "AREA HARVESTED"])].copy()
    d["year"] = d.YEAR.astype(int)
    d = d[d.year.between(Y0, Y1)]
    parsed = d.SHORT_DESC.map(parse_short)
    d = d[parsed.notna()].copy()
    parsed = parsed[parsed.notna()]
    d[["crop", "pri", "practice", "stat", "unit"]] = pd.DataFrame(parsed.tolist(), index=d.index)
    asd = d.ASD_CODE.str.strip()
    ca = d.COUNTY_ANSI.str.strip()
    agg = d.AGG_LEVEL_DESC
    d["agg_level"] = np.select(
        [(agg == "COUNTY") & (ca != ""), (agg == "COUNTY") & (ca == ""), agg == "AGRICULTURAL DISTRICT", agg == "STATE"],
        ["COUNTY", "DISTRICT_OTHER", "DISTRICT", "STATE"], "")
    d = d[~d.agg_level.isin(["DISTRICT", "DISTRICT_OTHER"]) | asd.isin(DISTRICTS)]
    asd = d.ASD_CODE.str.strip()
    d["county_fips"] = np.select(
        [d.agg_level == "COUNTY", d.agg_level == "DISTRICT_OTHER", d.agg_level == "DISTRICT"],
        ["20" + d.COUNTY_ANSI.str.strip().str.zfill(3), "20C" + asd, "20D" + asd], "20000")
    d["county_name"] = np.select(
        [d.agg_level == "COUNTY", d.agg_level == "DISTRICT_OTHER", d.agg_level == "DISTRICT"],
        [d.COUNTY_NAME.str.title(), "Other (combined) counties, " + d.ASD_DESC.str.title(), "District " +
         d.ASD_DESC.str.title()], "Kansas")
    d["asd_code"] = asd.where(d.agg_level != "STATE", "")
    d["value"] = d.VALUE.map(num)
    d["suppressed"] = d.VALUE.str.strip().isin(["(D)", "(Z)", "(NA)", "(X)", "(S)"])
    d["cv"] = pd.to_numeric(d["CV_%"].str.strip(), errors="coerce")
    # take the highest-priority crop description per key+stat (winter wheat over all wheat), latest load time
    d = d.sort_values(["pri", "LOAD_TIME"], ascending=[True, False])
    d = d.drop_duplicates(["county_fips", "year", "crop", "practice", "stat"], keep="first")
    key = ["county_fips", "county_name", "agg_level", "asd_code", "year", "crop", "practice"]
    y = d[d.stat == "yield"].set_index(key)
    a = d[d.stat == "harvested_acres"].set_index(key)
    out = pd.DataFrame({"yield": y.value, "yield_unit": y.unit, "yield_cv_pct": y.cv, "yield_raw": y.VALUE.str.strip(),
                        "nass_desc_yield": y.SHORT_DESC}).join(
        pd.DataFrame({"harvested_acres": a.value, "acres_raw": a.VALUE.str.strip(), "nass_desc_acres": a.SHORT_DESC}),
        how="outer").reset_index()
    out["yield_unit"] = out.yield_unit.fillna(out.crop.map(lambda c: "lb/ac" if c == "cotton" else "bu/ac"))
    out["source"] = "USDA NASS QuickStats bulk " + raw._SOURCE_URL.iloc[0].rsplit("/", 1)[-1] + \
                    " (SURVEY, annual, DOMAIN=TOTAL)"
    return out.sort_values(["agg_level", "county_fips", "crop", "practice", "year"]).reset_index(drop=True)


def prices(raw):
    p = raw[(raw.STATISTICCAT_DESC == "PRICE RECEIVED") & (raw.AGG_LEVEL_DESC == "STATE")
            & (raw.REFERENCE_PERIOD_DESC == "MARKETING YEAR") & (raw.DOMAIN_DESC == "TOTAL")].copy()
    want = {"CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU": ("corn", 1.0, "USD/bu"),
            "SORGHUM, GRAIN - PRICE RECEIVED, MEASURED IN $ / CWT": ("sorghum", 0.56, "USD/bu"),  # 56 lb per bushel
            "WHEAT, WINTER - PRICE RECEIVED, MEASURED IN $ / BU": ("wheat", 1.0, "USD/bu"),
            "SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU": ("soybeans", 1.0, "USD/bu"),
            "COTTON, UPLAND - PRICE RECEIVED, MEASURED IN $ / LB": ("cotton", 1.0, "USD/lb")}
    p = p[p.SHORT_DESC.isin(want)]
    p["year"] = p.YEAR.astype(int)
    p = p[p.year.between(2010, 2025)]
    p = p.sort_values("LOAD_TIME").drop_duplicates(["SHORT_DESC", "year"], keep="last")
    rows = []
    for _, r in p.iterrows():
        crop, f, unit = want[r.SHORT_DESC]
        v = num(r.VALUE)
        rows.append({"year": r.year, "crop": crop, "price": round(v * f, 4) if np.isfinite(v) else np.nan, "unit": unit,
                     "price_nass": v, "unit_nass": r.UNIT_DESC, "period": "MARKETING YEAR", "nass_desc": r.SHORT_DESC,
                     "nass_load_time": r.LOAD_TIME,
                     "source": "USDA NASS QuickStats bulk " + r._SOURCE_URL.rsplit("/", 1)[-1] + " (Kansas, SURVEY)"})
    return pd.DataFrame(rows).sort_values(["crop", "year"]).reset_index(drop=True)


def main():
    raw = pd.read_csv(RAW, sep="\t", dtype=str, keep_default_na=False)
    nc = yields_areas(raw)
    nc.to_parquet(OUT / "nass_county.parquet", index=False)
    print("nass_county.parquet", len(nc), "rows")
    cty = nc[nc.agg_level == "COUNTY"]
    cov = cty.groupby(["crop", "practice"]).agg(
        n_yield=("yield", lambda s: s.notna().sum()), n_acres=("harvested_acres", lambda s: s.notna().sum()),
        counties=("county_fips", "nunique"), y0=("year", "min"), y1=("year", "max"),
        last_yield_year=("year", lambda s: s[cty.loc[s.index, "yield"].notna()].max()))
    print(cov.to_string())
    print(nc[nc.agg_level != "COUNTY"].groupby(["agg_level", "crop", "practice"]).agg(
        n=("yield", lambda s: s.notna().sum()), y1=("year", "max")).to_string())
    pr = prices(raw)
    pr.to_parquet(OUT / "prices.parquet", index=False)
    print(pr.pivot(index="year", columns="crop", values="price").to_string())


if __name__ == "__main__":
    main()
