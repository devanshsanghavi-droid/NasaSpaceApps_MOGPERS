"""econ: per-acre production costs from USDA ERS Commodity Costs and Returns -> data/processed/costs.json

Source page: https://www.ers.usda.gov/data-products/commodity-costs-and-returns (CSV per commodity, updated 10/1/2026).
Regions kept: Prairie Gateway (covers western Kansas), Heartland, U.S. total. Years: 2016-2025 (latest = 2025).
ERS does not split irrigated vs dryland costs; it reports the share of irrigated/dryland acres in the survey base.
Run: python3 pipeline/econ_costs.py
"""
import json
from pathlib import Path

import pandas as pd
import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "ers"
OUT = APP / "data" / "processed" / "costs.json"
UA = {"User-Agent": "water-clock-hackathon"}
PAGE = "https://www.ers.usda.gov/data-products/commodity-costs-and-returns"
FILES = {"corn": "https://www.ers.usda.gov/media/4962/corn.csv",
         "cotton": "https://www.ers.usda.gov/media/4964/cotton.csv",
         "sorghum": "https://www.ers.usda.gov/media/4972/sorghum.csv",
         "soybeans": "https://www.ers.usda.gov/media/4976/soybeans.csv",
         "wheat": "https://www.ers.usda.gov/media/4978/wheat.csv"}
REGIONS = ["Prairie Gateway", "Heartland", "U.S. total"]
Y0 = 2016
ITEMS = {  # (Category, Item) -> output key
    ("Operating costs", "Total, operating costs"): "operating_usd_ac",
    ("Allocated overhead", "Total, allocated overhead"): "allocated_overhead_usd_ac",
    ("Costs listed", "Total, costs listed"): "total_costs_usd_ac",
    ("Allocated overhead", "Opportunity cost of land"): "land_opportunity_cost_usd_ac",
    ("Allocated overhead", "Capital recovery of machinery and equipment"): "capital_recovery_usd_ac",
    ("Operating costs", "Fuel, lube, and electricity"): "fuel_lube_electricity_usd_ac",
    ("Operating costs", "Purchased irrigation water"): "purchased_irrigation_water_usd_ac",
    ("Operating costs", "Seed"): "seed_usd_ac",
    ("Operating costs", "Fertilizer"): "fertilizer_usd_ac",
    ("Operating costs", "Chemicals"): "chemicals_usd_ac",
    ("Gross value of production", "Total, gross value of production"): "gross_value_usd_ac",
    ("Net value", "Value of production less operating costs"): "net_over_operating_usd_ac",
    ("Net value", "Value of production less total costs listed"): "net_over_total_usd_ac",
    ("Supporting information", "Yield"): "yield_per_planted_ac",
    ("Supporting information", "Price"): "harvest_price",
    ("Production practices", "Irrigated"): "irrigated_pct_of_acres",
    ("Production practices", "Dryland"): "dryland_pct_of_acres",
}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    out = {"source": "USDA ERS Commodity Costs and Returns", "source_page": PAGE, "files": FILES,
           "units": "USD per planted acre (nominal), except yield (per planted acre, bu or lb) and harvest price",
           "regions": REGIONS, "practice": "ALL (ERS does not publish irrigated vs dryland cost splits; "
                                             "irrigated_pct_of_acres gives the irrigated share of the region's survey base)",
           "notes": [
               "operating_usd_ac + allocated_overhead_usd_ac = total_costs_usd_ac.",
               "allocated overhead includes opportunity cost of land and unpaid labor and capital recovery; for a "
               "cash-cost view use operating_usd_ac.",
               "Prairie Gateway = ERS Farm Resource Region covering western Kansas, Oklahoma, Texas panhandle, eastern "
               "Colorado/New Mexico, southern Nebraska.",
               "No irrigated-specific cost source was reachable (KSU AgManager farm management guides at "
               "www.agmanager.info: proxy CONNECT 403). Pumping energy cost per acre-foot is not derived.",
               "Latest year (2025) values are ERS estimates based on the survey base year listed per crop.",
           ],
           "crops": {}}
    for crop, url in FILES.items():
        p = RAW / f"{crop}.csv"
        if not p.exists():
            r = requests.get(url, headers=UA, timeout=120)
            r.raise_for_status()
            p.write_bytes(r.content)
        d = pd.read_csv(p)
        d = d[d.Region.isin(REGIONS) & (d.Year >= Y0)]
        crop_out = {}
        for region in REGIONS:
            dr = d[d.Region == region]
            if dr.empty:
                continue
            years = {}
            for yr, g in dr.groupby("Year"):
                rec = {}
                for (cat, item), key in ITEMS.items():
                    v = g[(g.Category == cat) & (g.Item.str.strip() == item)]
                    if len(v):
                        rec[key] = round(float(v.Value.iloc[0]), 2)
                        if key in ("yield_per_planted_ac", "harvest_price"):
                            rec[key + "_unit"] = v.Units.iloc[0]
                rec["survey_base_year"] = str(g["Survey base year"].iloc[0])
                years[int(yr)] = rec
            latest = max(years)
            crop_out[region] = {"latest_year": latest, "latest": years[latest], "by_year": years}
        out["crops"][crop] = crop_out
        pg = crop_out.get("Prairie Gateway")
        if pg:
            l = pg["latest"]
            print(crop, pg["latest_year"], "operating", l.get("operating_usd_ac"), "overhead",
                  l.get("allocated_overhead_usd_ac"), "irrigated%", l.get("irrigated_pct_of_acres"))
        else:
            print(crop, "no Prairie Gateway rows; regions:", list(crop_out))
    OUT.write_text(json.dumps(out, indent=1))
    print("wrote", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
