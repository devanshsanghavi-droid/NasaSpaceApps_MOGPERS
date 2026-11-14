"""Build RMA county-year and state-year tables from cached raw files (run rma_fetch.py first).

Inputs (data/raw/rma/):
  colsom_YYYY.zip  Cause of Loss with month (30 pipe-delimited fields, layout
                   COL_Summary_of_Business_with_Month_All_Years.pdf)
  sobcov_YYYY.zip  Summary of Business state/county/crop/coverage level (28 fields,
                   SOB_State_County_Crop_with_Coverage_Level_1989_Forward.pdf)
  sobtpu_YYYY.zip  Summary of Business type/practice/unit structure (27 fields,
                   SOBTPU_External_All_Years.pdf). CR-only line endings.
Outputs (data/processed/):
  rma_county_year.parquet  key (fips, year, crop), 7 states, real counties only (county 999 excluded)
  rma_state_year.parquet   key (state_abbr, year, crop), 7 states + 'US' (all states and territories)

Usage: python pipeline/rma_build.py [--sanity]
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "rma"
OUT = ROOT / "data" / "processed"
YEARS = range(2001, 2026)

STATES = {"19": "IA", "31": "NE", "20": "KS", "29": "MO", "17": "IL", "46": "SD", "27": "MN"}
CROP_CODES = {"0041": "corn", "0081": "soybeans", "0011": "wheat", "0051": "sorghum"}
EXPECTED_NAMES = {"0041": "CORN", "0081": "SOYBEANS", "0011": "WHEAT", "0051": "GRAIN SORGHUM"}

# Cause of loss codes (field 12 of colsom), confirmed against field 13 descriptions in every year.
CAUSE_DROUGHT = {"11"}          # Drought
CAUSE_HEAT = {"12", "62"}       # Heat, Hot Wind
CAUSE_EXCESS_MOIST = {"31"}     # Excess Moisture/Precipitation/Rain

IRR_RE = re.compile(r"IRR", re.I)
NONIRR_RE = re.compile(r"NON[- ]?IRR", re.I)

COLS_OUT = [
    "insured_acres", "liability_usd", "premium_usd", "subsidy_usd", "indem_total_usd",
    "indem_drought_usd", "indem_heat_usd", "indem_excess_moist_usd", "det_acres_drought",
    "irrigated_insured_share", "lcr_drought", "drought_usd_per_ac",
]
SUM_COLS = [
    "insured_acres", "liability_usd", "premium_usd", "subsidy_usd", "indem_total_usd",
    "indem_drought_usd", "indem_heat_usd", "indem_excess_moist_usd", "det_acres_drought",
    "tpu_acres", "tpu_irr_acres",
]
KEY = ["state_fips", "county", "crop"]


def load(name: str, ncols: int) -> pd.DataFrame:
    with zipfile.ZipFile(RAW / name) as z:
        b = z.read(z.namelist()[0])
    b = b.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    df = pd.read_csv(io.BytesIO(b), sep="|", header=None, dtype=str, quoting=csv.QUOTE_NONE,
                     keep_default_na=False)
    if df.shape[1] != ncols:
        raise ValueError(f"{name}: expected {ncols} fields, got {df.shape[1]}")
    return df


def num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.strip(), errors="coerce").fillna(0.0)


def with_all(df: pd.DataFrame, cols: list[str], code_col: str = "comm") -> pd.DataFrame:
    """Sum to (state, county, crop) for the four target crops plus crop='all'."""
    crops = df[df[code_col].isin(CROP_CODES)].assign(crop=lambda d: d[code_col].map(CROP_CODES))
    a = crops.groupby(KEY, as_index=False)[cols].sum()
    b = df.assign(crop="all").groupby(KEY, as_index=False)[cols].sum()
    return pd.concat([a, b], ignore_index=True)


def check_names(df: pd.DataFrame, name_col: int, year: int, src: str, log: list[str]) -> None:
    for code, exp in EXPECTED_NAMES.items():
        names = {n.strip().upper() for n in df.loc[df["comm"] == code, name_col].unique()}
        if names and names != {exp}:
            log.append(f"{year} {src}: commodity {code} names {sorted(names)} (expected {exp})")


def build_year(y: int, log: list[str]) -> pd.DataFrame:
    # ---- Summary of Business with coverage level: acres, liability, premium, subsidy
    sob = load(f"sobcov_{y}.zip", 28)
    sob = sob.rename(columns={1: "state_fips", 3: "county", 5: "comm"})
    sob["state_fips"] = sob["state_fips"].str.strip().str.zfill(2)
    sob["county"] = sob["county"].str.strip().str.zfill(3)
    sob["comm"] = sob["comm"].str.strip().str.zfill(4)
    check_names(sob, 6, y, "sobcov", log)
    qtype = sob[17].str.strip()
    sob["insured_acres"] = np.where(qtype.str.lower() == "acres", num(sob[18]), 0.0)
    sob["liability_usd"] = num(sob[20])
    sob["premium_usd"] = num(sob[21])
    sob["subsidy_usd"] = num(sob[22])
    sob["sob_indem"] = num(sob[26])
    # commodities measured only in acres this year (for det_acres in crop='all')
    qt = sob.assign(q=qtype.str.lower()).groupby("comm")["q"].agg(lambda s: set(s))
    acre_comms = set(qt[qt.apply(lambda s: s == {"acres"})].index)
    s_agg = with_all(sob, ["insured_acres", "liability_usd", "premium_usd", "subsidy_usd", "sob_indem"])

    # ---- Cause of loss: indemnity by cause
    col = load(f"colsom_{y}.zip", 30)
    col = col.rename(columns={1: "state_fips", 3: "county", 5: "comm"})
    col["state_fips"] = col["state_fips"].str.strip().str.zfill(2)
    col["county"] = col["county"].str.strip().str.zfill(3)
    col["comm"] = col["comm"].str.strip().str.zfill(4)
    check_names(col, 6, y, "colsom", log)
    cause = col[11].str.strip().str.zfill(2)
    ind = num(col[28])
    det = num(col[27])
    col["indem_total_usd"] = ind
    col["indem_drought_usd"] = np.where(cause.isin(CAUSE_DROUGHT), ind, 0.0)
    col["indem_heat_usd"] = np.where(cause.isin(CAUSE_HEAT), ind, 0.0)
    col["indem_excess_moist_usd"] = np.where(cause.isin(CAUSE_EXCESS_MOIST), ind, 0.0)
    col["det_acres_drought"] = np.where(cause.isin(CAUSE_DROUGHT) & col["comm"].isin(acre_comms), det, 0.0)
    c_agg = with_all(col, ["indem_total_usd", "indem_drought_usd", "indem_heat_usd",
                           "indem_excess_moist_usd", "det_acres_drought"])

    # ---- Type/practice/unit: irrigated share of insured acres
    tpu = load(f"sobtpu_{y}.zip", 27)
    tpu = tpu.rename(columns={1: "state_fips", 4: "county", 6: "comm"})
    tpu["state_fips"] = tpu["state_fips"].str.strip().str.zfill(2)
    tpu["county"] = tpu["county"].str.strip().str.zfill(3)
    tpu["comm"] = tpu["comm"].str.strip().str.zfill(4)
    acres = np.where(tpu[20].str.strip().str.lower() == "acres", num(tpu[19]), 0.0)
    pname = tpu[16].str.strip()
    irr = pname.str.contains(IRR_RE) & ~pname.str.contains(NONIRR_RE)
    tpu["tpu_acres"] = acres
    tpu["tpu_irr_acres"] = np.where(irr, acres, 0.0)
    t_agg = with_all(tpu, ["tpu_acres", "tpu_irr_acres"])

    df = s_agg.merge(c_agg, on=KEY, how="outer").merge(t_agg, on=KEY, how="outer")
    num_cols = [c for c in df.columns if c not in KEY]
    df[num_cols] = df[num_cols].fillna(0.0)
    df["year"] = y

    tot_c, tot_s = df.loc[df.crop == "all", "indem_total_usd"].sum(), df.loc[df.crop == "all", "sob_indem"].sum()
    log.append(f"{y}: colsom indemnity ${tot_c/1e9:.3f}B vs sobcov ${tot_s/1e9:.3f}B; "
               f"sobtpu acres / sobcov acres (all) = "
               f"{df.loc[df.crop=='all','tpu_acres'].sum()/max(df.loc[df.crop=='all','insured_acres'].sum(),1):.3f}")
    return df.drop(columns=["sob_indem"])


def finish(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    with np.errstate(divide="ignore", invalid="ignore"):
        df["irrigated_insured_share"] = np.where(df.tpu_acres > 0, df.tpu_irr_acres / df.tpu_acres, np.nan)
        df["lcr_drought"] = np.where(df.liability_usd > 0, df.indem_drought_usd / df.liability_usd, np.nan)
        df["drought_usd_per_ac"] = np.where(df.insured_acres > 0, df.indem_drought_usd / df.insured_acres, np.nan)
    return df


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    log: list[str] = []
    frames = []
    for y in YEARS:
        frames.append(build_year(y, log))
        print(log[-1], flush=True)
    allc = pd.concat(frames, ignore_index=True)

    # county table: 7 states, real counties only
    cty = allc[allc.state_fips.isin(STATES) & (allc.county != "999")].copy()
    cty["fips"] = cty.state_fips + cty.county
    cty = finish(cty)
    cty = cty[["fips", "year", "crop"] + COLS_OUT].sort_values(["fips", "year", "crop"]).reset_index(drop=True)
    cty["year"] = cty["year"].astype("int32")

    # state table: all county records (incl. county 999 'All Other Counties') summed by state, plus US
    st = allc[allc.state_fips.isin(STATES)].groupby(["state_fips", "year", "crop"], as_index=False)[SUM_COLS].sum()
    st["state_abbr"] = st.state_fips.map(STATES)
    us = allc.groupby(["year", "crop"], as_index=False)[SUM_COLS].sum()
    us["state_fips"], us["state_abbr"] = "00", "US"
    st = finish(pd.concat([st, us], ignore_index=True))
    st = st[["state_abbr", "state_fips", "year", "crop"] + COLS_OUT].sort_values(
        ["state_abbr", "year", "crop"]).reset_index(drop=True)
    st["year"] = st["year"].astype("int32")

    cty.to_parquet(OUT / "rma_county_year.parquet", index=False)
    st.to_parquet(OUT / "rma_state_year.parquet", index=False)
    print(f"wrote rma_county_year.parquet {len(cty):,} rows, {cty.fips.nunique()} counties, "
          f"years {cty.year.min()}-{cty.year.max()}")
    print(f"wrote rma_state_year.parquet {len(st):,} rows")
    for line in log:
        if "commodity" in line:
            print("NAME CHECK:", line)
    if "--sanity" in sys.argv:
        sanity(st)


def sanity(st: pd.DataFrame) -> None:
    pd.set_option("display.width", 200)
    us = st[(st.state_abbr == "US") & (st.crop == "all")].set_index("year")
    t = pd.DataFrame({
        "indem_total_B": us.indem_total_usd / 1e9,
        "indem_drought_B": us.indem_drought_usd / 1e9,
        "drought_share": us.indem_drought_usd / us.indem_total_usd,
        "liability_B": us.liability_usd / 1e9,
        "premium_B": us.premium_usd / 1e9,
        "subsidy_B": us.subsidy_usd / 1e9,
        "subsidy_share": us.subsidy_usd / us.premium_usd,
    }).round(3)
    print("\nUS, all commodities:\n", t.to_string())
    print(f"\nUS drought 2001-2022 sum: ${us.loc[2001:2022,'indem_drought_usd'].sum()/1e9:.2f}B, "
          f"share of all indemnity {us.loc[2001:2022,'indem_drought_usd'].sum()/us.loc[2001:2022,'indem_total_usd'].sum():.3f}")
    for s, y in [("IA", 2012), ("NE", 2022), ("IA", 2022), ("NE", 2012)]:
        r = st[(st.state_abbr == s) & (st.year == y)].set_index("crop")
        print(f"\n{s} {y} (USD M):\n", (r[["indem_total_usd", "indem_drought_usd", "liability_usd"]] / 1e6).round(1).to_string())


if __name__ == "__main__":
    main()
