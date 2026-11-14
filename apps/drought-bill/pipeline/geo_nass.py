"""geo module: NASS county yields/acres and marketing-year prices for the 7 Drought Bill states, 2000-2025.

Source: USDA NASS QuickStats bulk file qs.crops_YYYYMMDD.txt.gz (https://www.nass.usda.gov/datasets/, ~1.1 GB gz).
The newest file name is scraped from the datasets page; the .gz is cached in data/raw/nass/ and streamed line by line
(never held in memory). Rows matching the filter are cached in data/raw/nass/rows_7state_survey_2000_2025.tsv.
Adapted from shared/central_iowa_pipeline/pipeline/context_nass.py.

Run: /home/user/venv-db/bin/python pipeline/geo_nass.py [--refresh]
Outputs (data/processed/):
  nass_county_year.parquet  key (fips, year, crop), crop in corn|soybeans|wheat|sorghum
  nass_prices.parquet       key (state_abbr, year, crop), state_abbr in 7 states + 'US'
See notes/geo.md for columns and caveats.
"""
import gzip
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "nass"
RAW.mkdir(parents=True, exist_ok=True)
PROC = ROOT / "data" / "processed"
PROC.mkdir(parents=True, exist_ok=True)
CACHE = RAW / "rows_7state_survey_2000_2025.tsv"
UA = {"User-Agent": "drought-bill-hackathon"}
STATES = {"IA": "19", "NE": "31", "KS": "20", "MO": "29", "IL": "17", "SD": "46", "MN": "27"}
COMMODITIES = {"CORN", "SOYBEANS", "WHEAT", "SORGHUM"}
STATS = {"YIELD", "AREA PLANTED", "AREA HARVESTED", "PRICE RECEIVED", "PRODUCTION"}
Y0, Y1 = 2000, 2025
SORGHUM_LB_PER_BU = 56.0  # NASS standard bushel weight for sorghum grain


def find_bulk_url():
    html = requests.get("https://www.nass.usda.gov/datasets", headers=UA, timeout=60).text
    m = re.findall(r'href="(/sites/default/files/datasets/qs\.crops_\d{8}\.txt\.gz)"', html)
    if not m:
        raise RuntimeError("qs.crops bulk file link not found on https://www.nass.usda.gov/datasets")
    return "https://www.nass.usda.gov" + sorted(m)[-1]


def get_bulk():
    local = sorted(RAW.glob("qs.crops_*.txt.gz"))
    if local and "--refresh" not in sys.argv and local[-1].stat().st_size > 900_000_000:
        return local[-1], "https://www.nass.usda.gov/sites/default/files/datasets/" + local[-1].name
    url = find_bulk_url()
    dst = RAW / url.rsplit("/", 1)[-1]
    print("downloading", url, flush=True)
    with requests.get(url, headers=UA, stream=True, timeout=300) as r:
        r.raise_for_status()
        with open(dst, "wb") as f:
            shutil.copyfileobj(r.raw, f, length=1 << 22)
    return dst, url


def open_lines(path):
    """Stream decompressed lines; prefer the external zcat (faster), fall back to gzip."""
    if shutil.which("zcat"):
        p = subprocess.Popen(["zcat", str(path)], stdout=subprocess.PIPE, text=True, encoding="utf-8",
                             errors="replace", bufsize=1 << 20)
        return p.stdout
    return gzip.open(path, "rt", encoding="utf-8", errors="replace", newline="")


def stream_filter(path):
    lines = open_lines(path)
    header = lines.readline().rstrip("\r\n").split("\t")
    ix = {h: i for i, h in enumerate(header)}
    keep, n = [], 0
    for line in lines:
        n += 1
        if n % 5_000_000 == 0:
            print(f"  {n:,} lines scanned, {len(keep):,} kept", flush=True)
        if not line.startswith("SURVEY\t"):
            continue
        f = line.rstrip("\r\n").split("\t")
        if len(f) != len(header) or f[ix["COMMODITY_DESC"]] not in COMMODITIES:
            continue
        if f[ix["STATISTICCAT_DESC"]] not in STATS:
            continue
        if not (f[ix["STATE_ALPHA"]] in STATES or f[ix["AGG_LEVEL_DESC"]] == "NATIONAL"):
            continue
        try:
            yr = int(f[ix["YEAR"]])
        except ValueError:
            continue
        if Y0 <= yr <= Y1:
            keep.append(f)
    print(f"done: {n:,} lines scanned, {len(keep):,} kept", flush=True)
    return pd.DataFrame(keep, columns=header)


def num(s):
    return pd.to_numeric(s.str.replace(",", "", regex=False).str.strip(), errors="coerce")


# (crop, practice) -> {quantity: SHORT_DESC}
def item_map():
    m = {}

    def add(crop, prac, base_y, base_pl, base_hv, base_pr):
        m[(crop, prac)] = {"yield": base_y, "planted": base_pl, "harvested": base_hv, "production": base_pr}

    for prac, tag in (("total", ""), ("irr", ", IRRIGATED"), ("nonirr", ", NON-IRRIGATED")):
        add("corn", prac, f"CORN, GRAIN{tag} - YIELD, MEASURED IN BU / ACRE", f"CORN{tag} - ACRES PLANTED",
            f"CORN, GRAIN{tag} - ACRES HARVESTED", f"CORN, GRAIN{tag} - PRODUCTION, MEASURED IN BU")
        add("soybeans", prac, f"SOYBEANS{tag} - YIELD, MEASURED IN BU / ACRE", f"SOYBEANS{tag} - ACRES PLANTED",
            f"SOYBEANS{tag} - ACRES HARVESTED", f"SOYBEANS{tag} - PRODUCTION, MEASURED IN BU")
        add("sorghum", prac, f"SORGHUM, GRAIN{tag} - YIELD, MEASURED IN BU / ACRE", f"SORGHUM{tag} - ACRES PLANTED",
            f"SORGHUM, GRAIN{tag} - ACRES HARVESTED", f"SORGHUM, GRAIN{tag} - PRODUCTION, MEASURED IN BU")
        add("wheat", prac, f"WHEAT{tag} - YIELD, MEASURED IN BU / ACRE", f"WHEAT{tag} - ACRES PLANTED",
            f"WHEAT{tag} - ACRES HARVESTED", f"WHEAT{tag} - PRODUCTION, MEASURED IN BU")
        for cls, cname in (("WHEAT, WINTER", "wheat_winter"), ("WHEAT, SPRING, (EXCL DURUM)", "wheat_spring"),
                           ("WHEAT, SPRING, DURUM", "wheat_durum")):
            add(cname, prac, f"{cls}{tag} - YIELD, MEASURED IN BU / ACRE", f"{cls}{tag} - ACRES PLANTED",
                f"{cls}{tag} - ACRES HARVESTED", f"{cls}{tag} - PRODUCTION, MEASURED IN BU")
    return m


def build_county(raw):
    c = raw[(raw.AGG_LEVEL_DESC == "COUNTY") & (raw.REFERENCE_PERIOD_DESC == "YEAR") & (raw.DOMAIN_DESC == "TOTAL")
            & (raw.COUNTY_ANSI.str.strip() != "")].copy()
    c["fips"] = c.STATE_FIPS_CODE.str.zfill(2) + c.COUNTY_ANSI.str.strip().str.zfill(3)
    c["year"] = c.YEAR.astype(int)
    c["v"] = num(c.VALUE)
    lut = {sd: (crop, prac, q) for (crop, prac), d in item_map().items() for q, sd in d.items()}
    c = c[c.SHORT_DESC.isin(lut)].copy()
    c[["crop", "prac", "q"]] = pd.DataFrame(c.SHORT_DESC.map(lut).tolist(), index=c.index)
    c = c.sort_values("LOAD_TIME").drop_duplicates(["fips", "year", "crop", "prac", "q"], keep="last")
    meta = c.groupby("fips").agg(state_abbr=("STATE_ALPHA", "first"), county_name=("COUNTY_NAME", "first"),
                                 asd_code=("ASD_CODE", "first"))
    w = c.pivot_table(index=["fips", "year", "crop"], columns=["prac", "q"], values="v", aggfunc="first")
    w.columns = [f"{q}_{p}" for p, q in w.columns]
    w = w.reset_index()
    for p in ("total", "irr", "nonirr"):
        for q in ("yield", "planted", "harvested", "production"):
            if f"{q}_{p}" not in w:
                w[f"{q}_{p}"] = np.nan

    main = w[w.crop.isin(["corn", "soybeans", "sorghum", "wheat"])].copy()
    main["wheat_method"] = np.where(main.crop == "wheat", "published_all_wheat", None)

    # wheat 2008+: NASS stopped publishing county all-wheat; sum the classes (winter, spring excl durum, durum)
    cls = w[w.crop.str.startswith("wheat_")].copy()
    cls = cls[cls.year >= 2008]
    have_all = set(map(tuple, main.loc[main.crop == "wheat", ["fips", "year"]].values))
    cls = cls[[(f, y) not in have_all for f, y in cls[["fips", "year"]].values]]
    cls["state_abbr"] = cls.fips.str[:2].map({v: k for k, v in STATES.items()})
    # classes published at county level anywhere in the state that year
    st_cls = cls.groupby(["state_abbr", "year"]).crop.agg(lambda s: set(s)).to_dict()
    rows = []
    for (f, y), g in cls.groupby(["fips", "year"]):
        rec = {"fips": f, "year": y, "crop": "wheat"}
        for p in ("total", "irr", "nonirr"):
            hv, pl, pr = g[f"harvested_{p}"], g[f"planted_{p}"], g[f"production_{p}"]
            rec[f"planted_{p}"] = pl.sum(min_count=1)
            rec[f"harvested_{p}"] = hv.sum(min_count=1)
            rec[f"production_{p}"] = pr.sum(min_count=1)
            ok = hv.notna() & pr.notna()
            # yield only if every class present has both production and harvested acres
            rec[f"yield_{p}"] = (pr.sum() / hv.sum()) if ok.all() and hv.sum() > 0 else np.nan
        present = set(g.crop)
        missing = st_cls.get((g.state_abbr.iloc[0], y), set()) - present
        rec["wheat_method"] = "sum_of_classes:" + "+".join(sorted(x.split("_")[1] for x in present)) + (
            " (missing at county level: " + "+".join(sorted(x.split("_")[1] for x in missing)) + ")" if missing else "")
        rows.append(rec)
    if rows:
        main = pd.concat([main, pd.DataFrame(rows)], ignore_index=True)

    main = main.join(meta, on="fips")
    out = main.rename(columns={
        "yield_total": "yield_bu_ac", "planted_total": "planted_ac", "harvested_total": "harvested_ac",
        "production_total": "production_bu",
        "yield_irr": "yield_irr_bu_ac", "planted_irr": "planted_irr_ac", "harvested_irr": "harvested_irr_ac",
        "production_irr": "production_irr_bu",
        "yield_nonirr": "yield_nonirr_bu_ac", "planted_nonirr": "planted_nonirr_ac",
        "harvested_nonirr": "harvested_nonirr_ac", "production_nonirr": "production_nonirr_bu"})
    out["county_name"] = out.county_name.str.title()
    cols = ["fips", "year", "crop", "state_abbr", "county_name", "asd_code", "yield_bu_ac", "planted_ac", "harvested_ac",
            "production_bu", "yield_irr_bu_ac", "yield_nonirr_bu_ac", "planted_irr_ac", "planted_nonirr_ac",
            "harvested_irr_ac", "harvested_nonirr_ac", "production_irr_bu", "production_nonirr_bu", "wheat_method"]
    out = out[cols].sort_values(["fips", "crop", "year"]).reset_index(drop=True)
    out["year"] = out.year.astype("int16")
    for col in cols[6:18]:
        out[col] = out[col].astype("float64")
    return out


PRICE_ITEMS = {
    "CORN, GRAIN - PRICE RECEIVED, MEASURED IN $ / BU": ("corn", 1.0),
    "SOYBEANS - PRICE RECEIVED, MEASURED IN $ / BU": ("soybeans", 1.0),
    "WHEAT - PRICE RECEIVED, MEASURED IN $ / BU": ("wheat", 1.0),
    "SORGHUM, GRAIN - PRICE RECEIVED, MEASURED IN $ / CWT": ("sorghum", SORGHUM_LB_PER_BU / 100.0),
}
MY_START_MONTH = {"corn": 9, "soybeans": 9, "sorghum": 9, "wheat": 6}  # US marketing year start month


def build_prices(raw):
    p = raw[(raw.STATISTICCAT_DESC == "PRICE RECEIVED") & (raw.REFERENCE_PERIOD_DESC == "MARKETING YEAR")
            & raw.SHORT_DESC.isin(PRICE_ITEMS) & raw.AGG_LEVEL_DESC.isin(["STATE", "NATIONAL"])].copy()
    p["state_abbr"] = np.where(p.AGG_LEVEL_DESC == "NATIONAL", "US", p.STATE_ALPHA)
    p["year"] = p.YEAR.astype(int)
    p["crop"] = p.SHORT_DESC.map(lambda s: PRICE_ITEMS[s][0])
    p["value_original"] = num(p.VALUE)
    p["unit_original"] = p.UNIT_DESC
    p["price_received_usd_per_bu"] = (p.value_original * p.SHORT_DESC.map(lambda s: PRICE_ITEMS[s][1])).round(4)
    p = p.sort_values("LOAD_TIME").drop_duplicates(["state_abbr", "year", "crop"], keep="last")
    lt = pd.to_datetime(p.LOAD_TIME, errors="coerce")
    my_end = pd.to_datetime([f"{y + 1}-{MY_START_MONTH[c]:02d}-01" for y, c in zip(p.year, p.crop)])
    p["preliminary"] = (lt < my_end).values  # loaded before the marketing year ended -> forecast/preliminary
    p["level"] = p.AGG_LEVEL_DESC.str.lower()
    out = p[["state_abbr", "year", "crop", "price_received_usd_per_bu", "value_original", "unit_original", "level",
             "preliminary", "LOAD_TIME"]].rename(columns={"LOAD_TIME": "nass_load_time"})
    out["year"] = out.year.astype("int16")
    return out.sort_values(["crop", "state_abbr", "year"]).reset_index(drop=True)


def main():
    if CACHE.exists() and "--refresh" not in sys.argv:
        raw = pd.read_csv(CACHE, sep="\t", dtype=str, keep_default_na=False)
    else:
        path, url = get_bulk()
        print("streaming", path, "from", url, flush=True)
        raw = stream_filter(path)
        raw["_SOURCE_FILE"] = path.name
        raw.to_csv(CACHE, sep="\t", index=False)
    print("filtered raw rows:", len(raw))

    cty = build_county(raw)
    cty.to_parquet(PROC / "nass_county_year.parquet", index=False)
    print("nass_county_year:", len(cty), "rows")
    print(cty.groupby("crop").agg(n=("yield_bu_ac", "size"), n_yield=("yield_bu_ac", "count"),
                                  counties=("fips", "nunique"), y0=("year", "min"), y1=("year", "max"),
                                  n_irr=("yield_irr_bu_ac", "count"), mean_yield=("yield_bu_ac", "mean")).to_string())

    pr = build_prices(raw)
    pr.to_parquet(PROC / "nass_prices.parquet", index=False)
    print("nass_prices:", len(pr), "rows")
    print(pr.pivot_table(index="year", columns=["crop"], values="price_received_usd_per_bu",
                         aggfunc=lambda s: s.iloc[-1]).tail(5))
    print(pr.groupby(["crop", "state_abbr"]).year.agg(["min", "max", "count"]).to_string())


if __name__ == "__main__":
    main()
