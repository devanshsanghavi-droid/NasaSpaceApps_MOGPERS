"""Download USGS High Plains aquifer base + 2009 saturated thickness from ScienceBase (cached in data/raw/usgs_hpa/)."""
import gzip
import shutil
import zipfile
from pathlib import Path

import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw" / "usgs_hpa"
UA = {"User-Agent": "water-clock-hackathon"}
SB = "https://www.sciencebase.gov/catalog/file/get/"
FILES = {
    # USGS OFR 98-393 base of aquifer contours (item 631405f5d34e36012efa35b2)
    "base/ofr98-393.e00.gz": "631405f5d34e36012efa35b2?f=__disk__9d%2F01%2F42%2F9d0142063d93b066ca4948b5d0e04485b1684b88",
    "base/ofr98-393_aqbase.xml": "631405f5d34e36012efa35b2?f=__disk__a4%2F42%2F9a%2Fa4429a571490fbc90abffc54ac0386f89daa8ea4",
    # USGS SIR 2012-5177 saturated thickness 2009 raster (item 631405d0d34e36012efa33aa)
    "sat09/hp_satthk09.zip": "631405d0d34e36012efa33aa?f=__disk__32%2F4b%2F28%2F324b28e38f480e2b553c2af632973c9d680922e9",
    "sat09/sir12-5177_hp_satthk09.xml": "631405d0d34e36012efa33aa?f=__disk__97%2F39%2F21%2F973921341db818780555347988a407875aa1e5fc",
}

if __name__ == "__main__":
    for rel, q in FILES.items():
        out = RAW / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists():
            r = requests.get(SB + q, headers=UA, timeout=600)
            r.raise_for_status()
            out.write_bytes(r.content)
        print(rel, out.stat().st_size)
    with gzip.open(RAW / "base/ofr98-393.e00.gz") as fi, open(RAW / "base/ofr98-393.e00", "wb") as fo:
        shutil.copyfileobj(fi, fo)
    zipfile.ZipFile(RAW / "sat09/hp_satthk09.zip").extractall(RAW / "sat09")
