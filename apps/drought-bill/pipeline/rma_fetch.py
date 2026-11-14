"""Download USDA RMA Cause of Loss (colsom) and Summary of Business (sobcov, sobtpu) files.

Raw zips and record-layout documents are cached in data/raw/rma/ and skipped when present.
Usage: python pipeline/rma_fetch.py [--force-recent]
  --force-recent  re-download 2021+ files (RMA keeps revising recent years).
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "rma"
BASE = "https://pubfs-rma.fpac.usda.gov/pub/Web_Data_Files/Summary_of_Business"
UA = {"User-Agent": "drought-bill-hackathon"}
MAX_WORKERS = 6

COL_YEARS = range(1989, 2026)  # colsom 1989-2025
SOBCOV_YEARS = range(2001, 2026)
SOBTPU_YEARS = range(2001, 2026)

DOCS = [
    f"{BASE}/cause_of_loss/COL_Summary_of_Business_with_Month_All_Years.pdf",
    f"{BASE}/cause_of_loss/COL_Summary_of_Business_with_Month_All_Years.doc",
    f"{BASE}/cause_of_loss/Stage_Code_Listing.xlsx",
    f"{BASE}/state_county_crop/SOB_State_County_Crop_with_Coverage_Level_1989_Forward.pdf",
    f"{BASE}/state_county_crop/SOBTPU_External_All_Years.pdf",
    f"{BASE}/state_county_crop/SOBTPU_External_All_Years.docx",
]


def targets() -> list[str]:
    urls = list(DOCS)
    urls += [f"{BASE}/cause_of_loss/colsom_{y}.zip" for y in COL_YEARS]
    urls += [f"{BASE}/state_county_crop/sobcov_{y}.zip" for y in SOBCOV_YEARS]
    urls += [f"{BASE}/state_county_crop/sobtpu_{y}.zip" for y in SOBTPU_YEARS]
    return urls


def fetch(url: str, force: bool = False) -> str:
    dest = RAW / url.rsplit("/", 1)[1]
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return f"cached {dest.name}"
    tmp = dest.with_suffix(dest.suffix + ".part")
    with requests.get(url, headers=UA, stream=True, timeout=120) as r:
        if r.status_code != 200:
            return f"FAILED {r.status_code} {url}"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    tmp.rename(dest)
    return f"downloaded {dest.name} ({dest.stat().st_size:,} B)"


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    force_recent = "--force-recent" in sys.argv

    def job(u: str) -> str:
        name = u.rsplit("/", 1)[1]
        yr = name.split("_")[-1].split(".")[0]
        force = force_recent and yr.isdigit() and int(yr) >= 2021
        try:
            return fetch(u, force)
        except Exception as e:  # noqa: BLE001
            return f"FAILED {u}: {e}"

    with ThreadPoolExecutor(MAX_WORKERS) as ex:
        for msg in ex.map(job, targets()):
            print(msg, flush=True)


if __name__ == "__main__":
    main()
