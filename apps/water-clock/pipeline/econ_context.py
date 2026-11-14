"""econ: county context -> data/processed/county_context.json

Per region county: Census population (Vintage 2025 estimates), largest incorporated places (Census Vintage 2025
sub-county estimates, place parts within county), and Census of Agriculture 2022 exposure measures (NASS bulk
qs.census2022.txt.gz, filtered by econ_nass_fetch.py).
No published "share of the local economy from irrigated agriculture" figure was reachable (BEA county earnings at
apps.bea.gov: proxy CONNECT 403), so that field is null; the Census of Ag measures are given instead with sources.
Run: python3 pipeline/econ_context.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw"
OUT = APP / "data" / "processed" / "county_context.json"
UA = {"User-Agent": "water-clock-hackathon"}
POP_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/counties/totals/co-est2025-alldata.csv"
SUB_URL = "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/cities/totals/sub-est2025_20.csv"
CENSUS_TSV = RAW / "nass" / "ks_census2022_rows.tsv"
CONTRACT = {
    "GMD1": ["071", "203", "171", "101"],
    "GMD3": ["075", "093", "055", "069", "057", "187", "067", "081", "129", "189", "175", "119"],
    "GMD4": ["023", "153", "039", "181", "193", "179", "199", "109", "063", "065"],
}
C2G = {c: g for g, cs in CONTRACT.items() for c in cs}

COA = {  # Census of Agriculture 2022 SHORT_DESC -> output key
    "AG LAND, IRRIGATED - ACRES": "irrigated_land_acres",
    "AG LAND, CROPLAND, HARVESTED, IRRIGATED - ACRES": "harvested_cropland_irrigated_acres",
    "AG LAND, CROPLAND, HARVESTED - ACRES": "harvested_cropland_acres",
    "AG LAND, CROPLAND - ACRES": "cropland_acres",
    "FARM OPERATIONS - ACRES OPERATED": "farm_acres_operated",
    "FARM OPERATIONS - NUMBER OF OPERATIONS": "farm_operations",
    "CROP TOTALS - SALES, MEASURED IN $": "crop_sales_usd",
    "ANIMAL TOTALS, INCL PRODUCTS - SALES, MEASURED IN $": "animal_sales_usd",
    "COMMODITY TOTALS - SALES, MEASURED IN $": "ag_sales_total_usd",
    "CORN - SALES, MEASURED IN $": "corn_sales_usd",
    "WHEAT - SALES, MEASURED IN $": "wheat_sales_usd",
    "SORGHUM - SALES, MEASURED IN $": "sorghum_sales_usd",
    "CORN, GRAIN, IRRIGATED - ACRES HARVESTED": "corn_grain_irrigated_acres",
    "CORN, GRAIN - ACRES HARVESTED": "corn_grain_acres",
    "WHEAT, IRRIGATED - ACRES HARVESTED": "wheat_irrigated_acres",
    "WHEAT - ACRES HARVESTED": "wheat_acres",
    "SORGHUM, GRAIN, IRRIGATED - ACRES HARVESTED": "sorghum_grain_irrigated_acres",
    "SORGHUM, GRAIN - ACRES HARVESTED": "sorghum_grain_acres",
    "SOYBEANS, IRRIGATED - ACRES HARVESTED": "soybeans_irrigated_acres",
    "SOYBEANS - ACRES HARVESTED": "soybeans_acres",
    "HAY, ALFALFA, IRRIGATED - ACRES HARVESTED": "alfalfa_irrigated_acres",
    "CORN, SILAGE, IRRIGATED - ACRES HARVESTED": "corn_silage_irrigated_acres",
    "INCOME, NET CASH FARM, OF OPERATIONS - NET INCOME, MEASURED IN $": "net_cash_farm_income_usd",
    "EXPENSE TOTALS, OPERATING - EXPENSE, MEASURED IN $": "operating_expense_usd",
    "GOVT PROGRAMS, FEDERAL - RECEIPTS, MEASURED IN $": "federal_program_receipts_usd",
}


def get(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = requests.get(url, headers=UA, timeout=120)
        r.raise_for_status()
        path.write_bytes(r.content)
    return path


def num(v):
    v = str(v).replace(",", "").strip()
    try:
        return float(v)
    except ValueError:
        return None


def main():
    pop = pd.read_csv(get(POP_URL, RAW / "census_pop" / "co-est2025-alldata.csv"), dtype=str, encoding="latin-1")
    pop = pop[(pop.STATE == "20") & pop.COUNTY.isin(C2G)].set_index("COUNTY")
    sub = pd.read_csv(get(SUB_URL, RAW / "census_pop" / "sub-est2025_20.csv"), dtype=str, encoding="latin-1")
    places = sub[(sub.SUMLEV == "157") & sub.COUNTY.isin(C2G) & ~sub.NAME.str.startswith("Balance of")
                 & ~sub.NAME.str.contains(r"\(balance\)")].copy()
    places["p25"] = places.POPESTIMATE2025.astype(int)

    coa = pd.read_csv(CENSUS_TSV, sep="\t", dtype=str, keep_default_na=False)
    coa_src = coa._SOURCE_URL.iloc[0]
    coa = coa[(coa.AGG_LEVEL_DESC == "COUNTY") & (coa.DOMAIN_DESC == "TOTAL") & (coa.YEAR == "2022")
              & coa.SHORT_DESC.isin(COA)]
    coa = coa.sort_values("LOAD_TIME").drop_duplicates(["COUNTY_ANSI", "SHORT_DESC"], keep="last")

    counties = []
    for c in sorted(C2G):
        p = pop.loc[c]
        pl = places[places.COUNTY == c].sort_values("p25", ascending=False).head(3)
        rec = {"fips": "20" + c, "name": p.CTYNAME.replace(" County", ""), "gmd": C2G[c],
               "population_2025": int(p.POPESTIMATE2025), "population_2020_base": int(p.ESTIMATESBASE2020),
               "population_change_2020_2025_pct": round(100 * (int(p.POPESTIMATE2025) / int(p.ESTIMATESBASE2020) - 1), 1),
               "main_towns": [{"name": r.NAME.replace(" (pt.)", "").replace(" city", ""), "population_2025": int(r.p25),
                               "part_in_county_only": "(pt.)" in r.NAME} for r in pl.itertuples()]}
        cc = coa[coa.COUNTY_ANSI.str.strip() == c]
        ag, raw = {}, {}
        for short, key in COA.items():
            v = cc[cc.SHORT_DESC == short]
            if len(v):
                raw[key] = v.VALUE.iloc[0].strip()
                ag[key] = num(v.VALUE.iloc[0])
            else:
                ag[key] = None
        sup = {k: v for k, v in raw.items() if num(v) is None}
        hc, hci = ag.get("harvested_cropland_acres"), ag.get("harvested_cropland_irrigated_acres")
        cg, cgi = ag.get("corn_grain_acres"), ag.get("corn_grain_irrigated_acres")
        der = {
            "irrigated_share_of_harvested_cropland": round(hci / hc, 3) if hc and hci is not None else None,
            "irrigated_share_of_corn_grain_acres": round(cgi / cg, 3) if cg and cgi is not None else None,
            "corn_share_of_irrigated_harvested_cropland": round(cgi / hci, 3) if hci and cgi is not None else None,
            "crop_sales_per_resident_usd": round(ag["crop_sales_usd"] / int(p.POPESTIMATE2025))
            if ag.get("crop_sales_usd") else None,
            "ag_sales_per_resident_usd": round(ag["ag_sales_total_usd"] / int(p.POPESTIMATE2025))
            if ag.get("ag_sales_total_usd") else None,
        }
        rec["census_of_ag_2022"] = ag
        if sup:
            rec["census_of_ag_2022_suppressed"] = sup
        rec["derived"] = der
        rec["share_of_economy_from_irrigated_ag"] = None
        counties.append(rec)
        print(rec["fips"], rec["name"], rec["population_2025"], [t["name"] for t in rec["main_towns"]],
              ag.get("irrigated_land_acres"), ag.get("crop_sales_usd"), der["irrigated_share_of_harvested_cropland"])

    out = {
        "sources": {
            "population": POP_URL + " (US Census Bureau, Vintage 2025 county population estimates, July 1 2025)",
            "main_towns": SUB_URL + " (Vintage 2025 subcounty estimates; SUMLEV 157 = incorporated place within county; "
                                    "top 3 by 2025 population)",
            "census_of_ag_2022": coa_src + " (USDA NASS 2022 Census of Agriculture, county level, DOMAIN=TOTAL)",
        },
        "notes": [
            "share_of_economy_from_irrigated_ag is null: no published county figure was reachable (BEA Regional "
            "CAINC5N farm earnings at apps.bea.gov returned proxy CONNECT 403). Use crop_sales_per_resident_usd, "
            "irrigated_share_of_harvested_cropland and irrigated_land_acres as exposure indicators instead.",
            "Values marked (D) by NASS (withheld to avoid disclosing individual operations) are null and listed in "
            "census_of_ag_2022_suppressed.",
            "Dollar values are 2022 nominal USD. Derived ratios are simple quotients of the cited values.",
            "Population is for the whole county; GMD membership follows CONTRACTS.md (see counties.geojson for the "
            "official-polygon check).",
        ],
        "counties": counties,
    }
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
