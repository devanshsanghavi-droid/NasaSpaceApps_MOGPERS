"""Shared paths and helpers for the Field to Faucet pipeline."""
from pathlib import Path
import time
import requests

APP = Path(__file__).resolve().parents[1]
RAW = APP / "data" / "raw"
PROC = APP / "data" / "processed"
WEB_DATA = APP / "web" / "data"
NOTES = APP / "notes"
for _p in (RAW, PROC, WEB_DATA, NOTES):
    _p.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "field-to-faucet-hackathon"}
STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
SITES = {"05484500": {"basin": "raccoon", "name": "Raccoon River at Van Meter, IA"},
         "05482000": {"basin": "desmoines", "name": "Des Moines River at 2nd Ave, Des Moines, IA"}}
MCL = 10.0
CFS_MGL_TO_KG_DAY = 2.4466

_session = requests.Session()
_session.headers.update(UA)


def get(url, params=None, retries=5, timeout=120, **kw):
    """GET with retries and backoff; raises on final failure."""
    last = None
    for a in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:  # network hiccup
            last = e
        time.sleep(2 ** a)
    raise last


def post(url, data=None, retries=5, timeout=180, **kw):
    last = None
    for a in range(retries):
        try:
            r = _session.post(url, data=data, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        except Exception as e:
            last = e
        time.sleep(2 ** a)
    raise last
