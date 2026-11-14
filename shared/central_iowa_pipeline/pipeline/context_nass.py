"""COUNTERFIELD context module: NASS county + state yields for Iowa (corn grain, soybeans), 2008-2024.

Streams the public QuickStats bulk file qs.crops_YYYYMMDD.txt.gz (~1.1 GB gz) and filters rows on the fly,
so the full file is never written to disk. Filtered raw rows are cached in data/raw/nass/ia_yield_rows.tsv.

Run: .venv/bin/python pipeline/context_nass.py  [--refresh]
Outputs:
  data/nass_county_yields.parquet   real counties only (agg_level COUNTY, county_fips = 5-digit FIPS); contract key
                                    county_fips,year,crop
  data/nass_iowa_aggregates.parquet same columns, non-county rows: COUNTY_OTHER_COMBINED ('19C'+ASD code),
                                    DISTRICT ('19D'+ASD code), STATE ('19000'). Use these to fill suppressed county-years.
"""
import gzip
import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nass"
RAW.mkdir(parents=True, exist_ok=True)
CACHE = RAW / "ia_yield_rows.tsv"
OUT = ROOT / "data" / "nass_county_yields.parquet"
OUT_AGG = ROOT / "data" / "nass_iowa_aggregates.parquet"
UA = {"User-Agent": "Mozilla/5.0 (counterfield-hackathon)"}

SHORT = {
    "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE": "corn",
    "SOYBEANS - YIELD, MEASURED IN BU / ACRE": "soybeans",
}
Y0, Y1 = 2008, 2024


def find_bulk_url():
    html = requests.get("https://www.nass.usda.gov/datasets", headers=UA, timeout=60).text
    m = re.findall(r'href="(/sites/default/files/datasets/qs\.crops_\d{8}\.txt\.gz)"', html)
    if not m:
        raise RuntimeError("qs.crops bulk file link not found on https://www.nass.usda.gov/datasets")
    return "https://www.nass.usda.gov" + sorted(m)[-1]


def stream_filter(url):
    print("streaming", url, flush=True)
    with requests.get(url, headers=UA, stream=True, timeout=120) as r:
        r.raise_for_status()
        r.raw.decode_content = False
        gz = gzip.GzipFile(fileobj=r.raw)
        txt = io.TextIOWrapper(gz, encoding="utf-8", errors="replace", newline="")
        header = txt.readline().rstrip("\r\n").split("\t")
        ix = {h: i for i, h in enumerate(header)}
        keep_rows = []
        n = 0
        for line in txt:
            n += 1
            if n % 5_000_000 == 0:
                print(f"  {n:,} lines scanned, {len(keep_rows)} kept", flush=True)
            # cheap prefilter before splitting
            if "\tIA\t" not in line or "YIELD" not in line:
                continue
            f = line.rstrip("\r\n").split("\t")
            if len(f) != len(header):
                continue
            if f[ix["STATE_ALPHA"]] != "IA":
                continue
            if f[ix["SHORT_DESC"]] not in SHORT:
                continue
            if f[ix["AGG_LEVEL_DESC"]] not in ("COUNTY", "STATE", "AGRICULTURAL DISTRICT"):
                continue
            if f[ix["SOURCE_DESC"]] != "SURVEY":
                continue
            if f[ix["STATISTICCAT_DESC"]] != "YIELD" or f[ix["UNIT_DESC"]] != "BU / ACRE":
                continue
            try:
                yr = int(f[ix["YEAR"]])
            except ValueError:
                continue
            if not (Y0 <= yr <= Y1):
                continue
            keep_rows.append(f)
        print(f"done: {n:,} lines scanned, {len(keep_rows)} kept", flush=True)
    df = pd.DataFrame(keep_rows, columns=header)
    df.attrs["source_url"] = url
    return df


def main():
    if CACHE.exists() and "--refresh" not in sys.argv:
        raw = pd.read_csv(CACHE, sep="\t", dtype=str, keep_default_na=False)
    else:
        url = find_bulk_url()
        raw = stream_filter(url)
        raw["_SOURCE_URL"] = url
        raw.to_csv(CACHE, sep="\t", index=False)
    print("raw filtered rows:", len(raw))
    raw = raw[raw["REFERENCE_PERIOD_DESC"] == "YEAR"].copy()  # drop in-season forecasts
    raw = raw[raw["DOMAIN_DESC"] == "TOTAL"]
    raw["value_num"] = pd.to_numeric(raw["VALUE"].str.replace(",", "").str.strip(), errors="coerce")
    raw["crop"] = raw["SHORT_DESC"].map(SHORT)
    raw["year"] = raw["YEAR"].astype(int)
    raw["asd_code"] = raw["ASD_CODE"].str.strip().str.zfill(2)
    is_cty = raw["AGG_LEVEL_DESC"] == "COUNTY"
    has_ansi = raw["COUNTY_ANSI"].str.strip() != ""
    # real counties
    cty = raw[is_cty & has_ansi].copy()
    cty["county_fips"] = cty["STATE_FIPS_CODE"].str.zfill(2) + cty["COUNTY_ANSI"].str.zfill(3)
    cty["county_name"] = cty["COUNTY_NAME"].str.title()
    cty["agg_level"] = "COUNTY"
    # "OTHER (COMBINED) COUNTIES" per crop-reporting district (counties NASS suppressed that year), pseudo key 19C<asd>
    oth = raw[is_cty & ~has_ansi].copy()
    oth["county_fips"] = "19C" + oth["asd_code"]
    asd_title = oth["ASD_DESC"].str.strip().str.title()
    oth["county_name"] = "Other (combined) counties, " + asd_title.where(asd_title != "", "statewide")
    oth["agg_level"] = "COUNTY_OTHER_COMBINED"
    # crop-reporting district totals, pseudo key 19D<asd>
    dis = raw[raw["AGG_LEVEL_DESC"] == "AGRICULTURAL DISTRICT"].copy()
    dis["county_fips"] = "19D" + dis["asd_code"]
    dis["county_name"] = "District " + dis["ASD_DESC"].str.title()
    dis["agg_level"] = "DISTRICT"
    st = raw[raw["AGG_LEVEL_DESC"] == "STATE"].copy()
    st["county_fips"] = "19000"
    st["county_name"] = "Iowa (state)"
    st["agg_level"] = "STATE"
    st["asd_code"] = ""
    cols = ["county_fips", "county_name", "year", "crop", "value_num", "agg_level", "asd_code", "ASD_DESC", "VALUE", "CV_%",
            "LOAD_TIME"]
    out = pd.concat([cty[cols], oth[cols], dis[cols], st[cols]], ignore_index=True)
    out = out.rename(columns={"value_num": "yield_bu_ac", "ASD_DESC": "asd",
                              "VALUE": "value_raw", "CV_%": "cv_pct", "LOAD_TIME": "nass_load_time"})
    out["source"] = "USDA NASS QuickStats bulk qs.crops (SURVEY, REFERENCE_PERIOD=YEAR, DOMAIN=TOTAL)"
    dup = out.duplicated(["county_fips", "year", "crop"], keep=False)
    if dup.any():
        print("WARNING duplicates:", out[dup].head())
        out = out.sort_values("nass_load_time").drop_duplicates(["county_fips", "year", "crop"], keep="last")
    out = out.sort_values(["agg_level", "county_fips", "crop", "year"]).reset_index(drop=True)
    is_c = out["agg_level"] == "COUNTY"
    out[is_c].reset_index(drop=True).to_parquet(OUT, index=False)
    out[~is_c].reset_index(drop=True).to_parquet(OUT_AGG, index=False)
    print(out.groupby(["agg_level", "crop"]).agg(n=("yield_bu_ac", "size"), n_null=("yield_bu_ac", lambda s: s.isna().sum()),
                                                 counties=("county_fips", "nunique"), mean=("yield_bu_ac", "mean"),
                                                 ymin=("year", "min"), ymax=("year", "max")))
    print("state:\n", out[out.agg_level == "STATE"].pivot(index="year", columns="crop", values="yield_bu_ac"))
    print("wrote", OUT, int(is_c.sum()), "rows;", OUT_AGG, int((~is_c).sum()), "rows")


if __name__ == "__main__":
    main()
