"""Strategy engine (farmer view): drought bill and income change per county x current rotation x strategy.

For every county with simulated corn and soybean loss-cost distributions and every rotation class used by the CDL
module (focus_fields.json), the script builds strategy cards:

  current        the rotation's drought bill ($/acre/yr expected, 1-in-5, 1-in-10)
  cc_to_cs       continuous corn -> corn-soybean (only when current = continuous corn)
  cs_small_grain corn-soybean-wheat (1/3 each) (current = corn-soy or continuous corn)
  cover_crop     cereal rye cover crop: drought-bill effect NOT quantified (bill shown unchanged)
  dt_sorghum     sorghum in place of corn (where the county/state insures sorghum)
  dt_wheat       wheat in place of corn (where sorghum is not an established insured crop)

Drought bill. The per-crop simulated loss-cost distributions (model/outputs/sim_county_crop.parquet: today's county
under each NASA POWER weather year 1981-2024) are combined WITHIN each hazard year (crop weights = share of the crop
in the rotation, each crop's $/acre = simulated loss cost ratio x county 2020-2024 liability per insured acre of that
crop), then mean / 80th / 90th percentile over the 44 years. Intervals: when model/outputs/sim_state.pkl.gz (the 100
bootstrap refits of the loss model) is present, every rotation and every delta is recomputed per bootstrap draw, so
lo/hi are 5th/95th percentiles of correctly correlated draws. Otherwise lo/hi come from the per-year 5th/95th
percentiles in sim_county_crop (approximate; method recorded in the outputs).

Rotation scenario (labelled, not estimated): corn grown in a 3+ crop rotation (or after soybean when leaving
continuous corn) loses a fraction r less in drought years; r = model/outputs/diversity_effect.json app_effect
(est 0.14 / lo 0 / hi 0.90, Bowles et al. 2020 trial range; the county data showed no robust effect).

Income: NASS county yields (state, then same-ERS-region states, then US when suppressed) x NASS state marketing-year
prices (US when missing) minus USDA ERS Commodity Costs and Returns operating costs (per planted acre, by ERS region),
each year 2019-2023; est = mean of the yearly deltas, lo/hi = min/max over the 5 years under the low/high
evidence assumptions (rotation yield effects from shared/evidence/evidence_priors.json).

Outputs: web/data/strategies.json (compact schema, see notes/strategy.md), model/outputs/strategies_summary.json.
Run: /home/user/venv-db/bin/python model/strategy.py   (~2-3 min; re-runnable; downloads ERS CSVs once)
"""
from __future__ import annotations

import gzip
import json
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "model"))
PROC = ROOT / "data" / "processed"
OUT = ROOT / "model" / "outputs"
WEB = ROOT / "web" / "data"
RAW_ERS = ROOT / "data" / "raw" / "ers"
NASS_TSV = ROOT / "data" / "raw" / "nass" / "rows_7state_survey_2000_2025.tsv"
PRIORS = ROOT.parents[1] / "shared" / "evidence" / "evidence_priors.json"

INC_YEARS = [2019, 2020, 2021, 2022, 2023]
SORGHUM_STATE_MIN_ACRES = 20_000   # state 2020-2024 mean insured sorghum acres to count as a sorghum state
STATE_LIAB_MIN_ACRES = 10_000      # state insured acres/yr needed to use the state's liability per acre
ERS_REGION = {"IA": "Heartland", "IL": "Heartland", "MN": "Heartland", "MO": "Heartland",
              "KS": "Prairie Gateway", "NE": "Prairie Gateway", "SD": "Northern Great Plains"}
ERS_FILES = {"corn": "https://www.ers.usda.gov/media/4962/corn.csv",
             "soybeans": "https://www.ers.usda.gov/media/4976/soybeans.csv",
             "wheat": "https://www.ers.usda.gov/media/4978/wheat.csv",
             "sorghum": "https://www.ers.usda.gov/media/4972/sorghum.csv"}
ERS_PAGE = "https://www.ers.usda.gov/data-products/commodity-costs-and-returns"
ERS_COVER = "https://www.ers.usda.gov/publications/pub-details?pubid=100550"  # EIB-222 (cached PDF in data/raw/ers)
NASS_YIELD = {"corn": "CORN, GRAIN - YIELD, MEASURED IN BU / ACRE", "soybeans": "SOYBEANS - YIELD, MEASURED IN BU / ACRE",
              "wheat": "WHEAT - YIELD, MEASURED IN BU / ACRE", "sorghum": "SORGHUM, GRAIN - YIELD, MEASURED IN BU / ACRE"}
BU_PER_T_HA = 1 / 0.06277          # bu/ac per t/ha for corn (56 lb/bu), as in evidence_priors E5 conversion note
# ERS EIB-222 Table 3 (ARMS): cover crop seed cost, rye, $/acre +- (corn fields 2016; soybean fields 2018)
RYE_SEED = {"corn": (14.26, 2.03), "soybeans": (16.27, 5.96)}
FIELDS = ["expected_bill", "bill_1in5", "bill_1in10", "delta_bill", "delta_bill_1in10", "delta_income_per_ac"]

# rotation classes (labels exactly as in web/data/focus_fields.json)
# parts: (crop, weight, tag); tag "simple" = corn in a simple rotation (no scenario), "div" = corn that gets the
# rotation scenario (1 - r), "cc" = continuous-corn corn (income: CC yield penalty), "" = other crops
ROTATIONS = {
    "corn-soy": {"parts": [("corn", 1 / 2, "simple"), ("soybeans", 1 / 2, "")],
                 "mix": "1/2 corn + 1/2 soybeans"},
    "continuous corn": {"parts": [("corn", 1.0, "cc")], "mix": "corn every year"},
    "3+ crop": {"parts": [("corn", 1 / 3, "div"), ("soybeans", 1 / 3, ""), ("wheat", 1 / 3, "")],
                "mix": "1/3 corn + 1/3 soybeans + 1/3 wheat (small grain); corn gets the rotation scenario"},
    "with perennial": {"parts": [("corn", 1 / 2, "div"), ("soybeans", 1 / 2, "")],
                       "mix": "corn and soybean years only (1/2 + 1/2); hay/alfalfa years are not in the drought "
                              "bill (no county forage model); corn gets the rotation scenario"},
}


# ---------------------------------------------------------------------------------------------- helpers
def rnd(x):
    if x is None or not np.isfinite(x):
        return None
    a = abs(x)
    if a < 10:
        return round(float(x), 2)
    if a < 100:
        return round(float(x), 1)
    return int(round(float(x)))


def trip(est, lo, hi):
    lo2 = min(lo, est) if np.isfinite(lo) else lo
    hi2 = max(hi, est) if np.isfinite(hi) else hi
    return [rnd(est), rnd(lo2), rnd(hi2)]


def load_priors():
    d = json.load(open(PRIORS))
    return {p["prior_id"]: p for p in d["priors"]}


def ensure_ers():
    """Download (once) the ERS Commodity Costs and Returns CSVs. Returns {crop: path or None}."""
    import requests
    RAW_ERS.mkdir(parents=True, exist_ok=True)
    out = {}
    for crop, url in ERS_FILES.items():
        p = RAW_ERS / f"{crop}.csv"
        if not p.exists() or p.stat().st_size < 10_000:
            try:
                r = requests.get(url, headers={"User-Agent": "drought-bill-hackathon"}, timeout=120)
                r.raise_for_status()
                p.write_bytes(r.content)
            except Exception as e:  # noqa: BLE001
                print(f"ERS download failed for {crop}: {e}")
                out[crop] = None
                continue
        out[crop] = p
    return out


def ers_costs(paths):
    """{(region, crop, year): total operating cost $/planted acre} (latest survey base per year)."""
    rows = {}
    meta = {}
    for crop, p in paths.items():
        if p is None:
            continue
        d = pd.read_csv(p)
        d = d[(d.Item == "Total, operating costs") & d.Year.isin(INC_YEARS)]
        d = d.assign(base=d["Survey base year"].str.extract(r"(\d{4})").astype(float))
        d = d.sort_values("base").drop_duplicates(["Region", "Year"], keep="last")
        for r in d.itertuples():
            rows[(r.Region, crop, int(r.Year))] = float(r.Value)
        meta[crop] = sorted(d.Region.unique().tolist())
    return rows, meta


def cost_region(state, crop, costs):
    reg = ERS_REGION[state]
    if all((reg, crop, y) in costs for y in INC_YEARS):
        return reg
    if all(("Prairie Gateway", crop, y) in costs for y in INC_YEARS):
        return "Prairie Gateway"
    return "U.S. total"


def state_yields():
    """Official NASS state and national yields (bu/ac) from the geo module's cached QuickStats rows."""
    t = pd.read_csv(NASS_TSV, sep="\t", dtype=str,
                    usecols=["AGG_LEVEL_DESC", "STATE_ALPHA", "SHORT_DESC", "DOMAIN_DESC", "REFERENCE_PERIOD_DESC",
                             "YEAR", "VALUE"])
    inv = {v: k for k, v in NASS_YIELD.items()}
    t = t[t.AGG_LEVEL_DESC.isin(["STATE", "NATIONAL"]) & t.SHORT_DESC.isin(inv) & (t.DOMAIN_DESC == "TOTAL")
          & (t.REFERENCE_PERIOD_DESC == "YEAR")]
    t = t.assign(crop=t.SHORT_DESC.map(inv), year=t.YEAR.astype(int),
                 v=pd.to_numeric(t.VALUE.str.replace(",", ""), errors="coerce"),
                 st=np.where(t.AGG_LEVEL_DESC == "NATIONAL", "US", t.STATE_ALPHA))
    t = t[t.year.isin(INC_YEARS)].dropna(subset=["v"])
    return {(r.st, r.crop, r.year): r.v for r in t.itertuples()}


# ---------------------------------------------------------------------------------------------- inputs
def load_inputs():
    sc = pd.read_parquet(OUT / "sim_county_crop.parquet")
    cs = pd.read_parquet(PROC / "county_static.parquet").set_index("fips")
    cty = pd.read_parquet(PROC / "counties.parquet").set_index("fips")
    rs = pd.read_parquet(PROC / "rma_state_year.parquet")
    bill = json.load(open(WEB / "county_bill.json"))
    reg = json.load(open(WEB / "regional_summary.json"))
    div = json.load(open(OUT / "diversity_effect.json"))
    nass = pd.read_parquet(PROC / "nass_county_year.parquet")
    prices = pd.read_parquet(PROC / "nass_prices.parquet")
    return sc, cs, cty, rs, bill, reg, div, nass, prices


def state_crop_tables(rs):
    r = rs[rs.year.between(2020, 2024)]
    g = r.groupby(["state_abbr", "crop"]).agg(liab=("liability_usd", "sum"), ac=("insured_acres", "sum"))
    irr = r.assign(ia=r.irrigated_insured_share.fillna(0) * r.insured_acres).groupby(["state_abbr", "crop"]).ia.sum()
    g["lpa"] = g.liab / g.ac.replace(0, np.nan)
    g["ac_yr"] = g.ac / 5
    g["irr"] = irr / g.ac.replace(0, np.nan)
    return g


def bootstrap_matrix(sc, synth_rows):
    """Return (mode, L, Ls): L = (draws, len(sc)) lcr per bootstrap draw aligned with sc rows (draw 0 = point model),
    Ls = same for the synthesised rows. mode 'bootstrap' or 'approx' (no sim_state: draws = point, lo, hi)."""
    p = OUT / "sim_state.pkl.gz"
    if p.exists():
        try:
            from lossmodel import predict
            with gzip.open(p, "rb") as fh:
                st = pickle.load(fh)
            sf, cfg, models = st["sf"], st["cfg"], st["models"]
            same = (len(sf) == len(sc) and (sf.fips.to_numpy() == sc.fips.to_numpy()).all()
                    and (sf.crop.to_numpy() == sc.crop.to_numpy()).all()
                    and (sf.hazard_year.to_numpy() == sc.hazard_year.to_numpy()).all())
            if same:
                p0 = predict(cfg, models[0][0], sf)
                if np.allclose(p0, sc.lcr_sim.to_numpy(), atol=1e-9):
                    L = np.empty((len(models), len(sf)))
                    L[0] = p0
                    syn = build_synth(sf, synth_rows) if len(synth_rows) else None
                    Ls = np.empty((len(models), 0 if syn is None else len(syn)))
                    for b, (m, _) in enumerate(models):
                        if b:
                            L[b] = predict(cfg, m, sf)
                        if syn is not None:
                            Ls[b] = predict(cfg, m, syn)
                    return "bootstrap", L, Ls, syn
            print("sim_state.pkl.gz does not match sim_county_crop.parquet -> approximate intervals")
        except Exception as e:  # noqa: BLE001
            print(f"bootstrap models unusable ({e}) -> approximate intervals")
    L = np.stack([sc.lcr_sim.to_numpy(), sc.lcr_sim_lo.to_numpy(), sc.lcr_sim_hi.to_numpy()])
    return "approx", L, None, None


def build_synth(sf, synth_rows):
    """Rows for county x crop with no 2020-2024 liability: copy the county's corn rows (same hazard years and static
    features), set the crop and the state's irrigated insured share of that crop. The credibility factor of an unseen
    county-crop is 1, i.e. a state/region-pooled model response to the county's own weather."""
    from lossmodel import CROP_CODE
    parts = []
    for fips, crop, irr in synth_rows:
        b = sf[(sf.fips == fips) & (sf.crop == "corn")].copy()
        b["crop"] = crop
        b["crop_code"] = CROP_CODE[crop]
        b["irrigated_insured_share"] = irr
        parts.append(b)
    return pd.concat(parts, ignore_index=True).sort_values(["fips", "crop", "hazard_year"]).reset_index(drop=True)


# ---------------------------------------------------------------------------------------------- bill maths
def stats3(S):
    """S (..., 44) -> mean, p80, p90 over the last axis."""
    return S.mean(-1), np.percentile(S, 80, axis=-1), np.percentile(S, 90, axis=-1)


def rot_series(parts, D, rs_):
    """parts [(crop, w, tag)], D {crop: (draws, 44) $/ac}, rs_ array of r -> (nr, draws, 44)."""
    tot = 0.0
    for crop, w, tag in parts:
        m = (1 - rs_ * (tag == "div"))[:, None, None]
        tot = tot + w * m * D[crop][None]
    return tot


def interval(A, mode):
    """A (nr, draws) with r index 0 = est, draw 0 = point model -> (lo, hi) envelope over r."""
    if mode == "bootstrap":
        return np.percentile(A[:, 1:], 5, axis=1).min(), np.percentile(A[:, 1:], 95, axis=1).max()
    return A.min(), A.max()


# ---------------------------------------------------------------------------------------------- main
def main():
    t0 = time.time()
    P = load_priors()
    sc, cs, cty, rs, bill, reg, div, nass, prices = load_inputs()
    app = div["app_effect"]
    R = np.array([app["r"]["est"], app["r"]["lo"], app["r"]["hi"]])  # index 0 = est
    stt = state_crop_tables(rs)
    sorghum_states = sorted(s for s in ERS_REGION if (s, "sorghum") in stt.index
                            and stt.loc[(s, "sorghum"), "ac_yr"] >= SORGHUM_STATE_MIN_ACRES)

    def state_lpa(state, crop):
        if (state, crop) in stt.index and stt.loc[(state, crop), "ac_yr"] >= STATE_LIAB_MIN_ACRES:
            return float(stt.loc[(state, crop), "lpa"]), "state"
        return float(stt.loc[("US", crop), "lpa"]), "US"

    # ---- which county-crops exist; which counties are eligible; which rows must be synthesised
    key = sc.drop_duplicates(["fips", "crop"]).set_index(["fips", "crop"])
    fips_all = sorted(sc.fips.unique())
    elig, synth, plan = [], [], {}
    for f in fips_all:
        st_ = key.loc[(f, "corn"), "state_abbr"] if (f, "corn") in key.index else None
        if st_ is None or (f, "soybeans") not in key.index or not key.loc[(f, "corn"), "enough_history"]:
            continue
        elig.append(f)
        has = lambda c: (f, c) in key.index  # noqa: E731
        enough = lambda c: has(c) and bool(key.loc[(f, c), "enough_history"])  # noqa: E731
        if enough("sorghum") or (st_ in sorghum_states):
            dt = "dt_sorghum"
        else:
            dt = "dt_wheat"
        plan[f] = {"state": st_, "dt": dt}
        for c in ["wheat"] + (["sorghum"] if dt == "dt_sorghum" else []):
            if not has(c):
                irr = stt.loc[(st_, c), "irr"] if (st_, c) in stt.index else np.nan
                synth.append((f, c, float(irr) if np.isfinite(irr) else 0.0))
    print(f"eligible counties {len(elig)} of {len(fips_all)}; synthesised county-crops {len(synth)}", flush=True)

    mode, L, Ls, syn = bootstrap_matrix(sc, synth)
    print(f"interval mode: {mode}; draws {L.shape[0]} ({time.time() - t0:.0f}s)", flush=True)

    # index rows: (fips, crop) -> row indices sorted by hazard year
    idx = {k: np.asarray(v) for k, v in sc.sort_values("hazard_year").groupby(["fips", "crop"]).groups.items()}
    sidx = {k: np.asarray(v) for k, v in syn.sort_values("hazard_year").groupby(["fips", "crop"]).groups.items()} \
        if syn is not None else {}

    def crop_D(f, c):
        """(draws, 44) $/ac, source tag, liability/acre."""
        if (f, c) in idx:
            ii = idx[(f, c)]
            lpa = float(sc.loc[ii[0], "liab_per_ac_recent"])
            src = "county" if bool(sc.loc[ii[0], "enough_history"]) else "thin"
            return L[:, ii] * lpa, src, lpa
        if (f, c) in sidx:
            lpa, lsrc = state_lpa(plan[f]["state"], c)
            return Ls[:, sidx[(f, c)]] * lpa, "pooled" if lsrc == "state" else "pooled_us", lpa
        if mode == "approx":  # fallback without bootstrap models: state-pooled ratio to the county's corn loss cost
            st_ = plan[f]["state"]
            pool = sc[(sc.state_abbr == st_) & sc.enough_history]
            g = pool.groupby(["fips", "crop"]).lcr_sim.mean().unstack()
            if c in g and g[c].notna().sum() >= 3:
                both = g[["corn", c]].dropna()
            else:
                g = sc[sc.enough_history].groupby(["fips", "crop"]).lcr_sim.mean().unstack()
                both = g[["corn", c]].dropna()
            ratio = both[c].sum() / both["corn"].sum()
            ii = idx[(f, "corn")]
            lpa, lsrc = state_lpa(st_, c)
            return L[:, ii] * ratio * lpa, "pooled_ratio", lpa
        return None, None, None

    # ---- income inputs
    ers_paths = ensure_ers()
    costs, ers_meta = ers_costs(ers_paths)
    have_costs = all(ers_paths.get(c) is not None for c in ERS_FILES)
    sy = state_yields()
    cy = {(r.fips, r.crop, int(r.year)): r.yield_bu_ac for r in
          nass[nass.year.isin(INC_YEARS) & nass.yield_bu_ac.notna()].itertuples()}
    pr = {(r.state_abbr, r.crop, int(r.year)): r.price_received_usd_per_bu for r in
          prices[prices.year.isin(INC_YEARS)].itertuples()}
    region_states = {}
    for s_, rg in ERS_REGION.items():
        region_states.setdefault(rg, []).append(s_)

    def yields(f, state, crop):
        out, nsrc = [], {"county": 0, "state": 0, "region": 0, "US": 0}
        for y in INC_YEARS:
            v = cy.get((f, crop, y))
            if v is not None and np.isfinite(v):
                out.append(v); nsrc["county"] += 1; continue
            v = sy.get((state, crop, y))
            if v is not None:
                out.append(v); nsrc["state"] += 1; continue
            nb = [sy[(s2, crop, y)] for s2 in region_states[ERS_REGION[state]] if (s2, crop, y) in sy]
            if nb:
                out.append(float(np.mean(nb))); nsrc["region"] += 1; continue
            out.append(sy[("US", crop, y)]); nsrc["US"] += 1
        top = "county" if nsrc["county"] >= 3 else max(("state", "region", "US"), key=lambda k: nsrc[k])
        return np.array(out, float), top

    def price(state, crop):
        out, us = [], 0
        for y in INC_YEARS:
            v = pr.get((state, crop, y))
            if v is None or not np.isfinite(v):
                v = pr[("US", crop, y)]; us += 1
            out.append(v)
        return np.array(out, float), us >= 3

    def cost(state, crop):
        if not have_costs:
            return np.zeros(len(INC_YEARS)), None
        rg = cost_region(state, crop, costs)
        return np.array([costs[(rg, crop, y)] for y in INC_YEARS]), rg

    # rotation yield-effect assumptions (est / lo / hi), all from evidence_priors.json
    k22 = P["E5_corn_kluger2022"]["effect"]
    beta_t = k22["mean"]                                     # 1.03 t/ha corn after soy vs corn after corn
    beta_lo = P["E5_corn_kluger2025"]["effect"]["mean"] / 100  # 2.5% of mean yield (net, observational)
    beta_hi = P["E5_corn_alkaisi2015"]["effect"]["mean"] / 100  # 18.5% of CC yield (Iowa trial, Ames)
    div_corn = {"est": 0.0, "lo": P["E4_corn_divers_kluger2025"]["effect"]["mean"] / 100,
                "hi": P["E4_corn_yield_davis2012"]["effect"]["mean"] / 100}
    div_soy = {"est": 0.0, "lo": 0.0, "hi": P["E4_soy_yield_davis2012"]["effect"]["mean"] / 100}
    cov_corn_vals = [P["E1_corn_yield_pantoja"]["effect"]["mean"], P["E1_corn_yield_marcillo"]["effect"]["mean"]]
    cov_corn = {"est": float(np.mean(cov_corn_vals)) / 100, "lo": min(cov_corn_vals) / 100, "hi": max(cov_corn_vals) / 100}
    cov_soy = {"est": P["E1_soy_yield_pantoja"]["effect"]["mean"] / 100,
               "lo": P["E1_yield_he2025_us"]["effect"]["mean"] / 100, "hi": P["E1_soy_yield_pantoja"]["effect"]["mean"] / 100}

    def cc_yield(Y, a):
        if a == "est":
            return Y - beta_t * BU_PER_T_HA
        if a == "lo":
            return Y * (1 - beta_lo)
        return Y / (1 + beta_hi)

    def rot_income(parts, NRin, a, cover=False, beta_a="est"):
        """Yearly net return $/ac of the rotation. NRin[crop] = (Y, price, cost) arrays."""
        tot = np.zeros(len(INC_YEARS))
        for crop, w, tag in parts:
            Y, Pz, C = NRin[crop]
            if tag == "cc":
                Y = cc_yield(Y, beta_a)
            elif tag == "div" and crop == "corn":
                Y = Y * (1 + div_corn[a])
            if tag == "div_soy":
                Y = Y * (1 + div_soy[a])
            extra = 0.0
            if cover and crop in ("corn", "sorghum", "soybeans"):
                eff = cov_soy[a] if crop == "soybeans" else cov_corn[a]
                Y = Y * (1 + eff)
                s, se = RYE_SEED["soybeans" if crop == "soybeans" else "corn"]
                extra = s + (se if a == "lo" else -se if a == "hi" else 0.0)
            tot = tot + w * (Y * Pz - C - extra)
        return tot

    # strategy rotations per current class
    def targets(cur, dt):
        sw = "sorghum" if dt == "dt_sorghum" else "wheat"
        t = {}
        if cur == "continuous corn":
            t["cc_to_cs"] = [("corn", 1 / 2, "cs_from_cc"), ("soybeans", 1 / 2, "")]
        if cur in ("corn-soy", "continuous corn"):
            t["cs_small_grain"] = [("corn", 1 / 3, "div"), ("soybeans", 1 / 3, "div_soy"), ("wheat", 1 / 3, "")]
        t["cover_crop"] = None
        if cur == "3+ crop":
            t[dt] = ([("sorghum", 1 / 3, ""), ("soybeans", 1 / 3, ""), ("wheat", 1 / 3, "")] if sw == "sorghum"
                     else [("wheat", 1 / 2, ""), ("soybeans", 1 / 2, "")])
        else:
            t[dt] = [(sw, 1 / 2, ""), ("soybeans", 1 / 2, "")]
        return t

    # ---- county loop
    counties_out, summ_rows = {}, []
    bc = bill.get("counties", {})
    for f in elig:
        st_ = plan[f]["state"]
        dt = plan[f]["dt"]
        D, src, lpa = {}, {}, {}
        for c in ["corn", "soybeans", "wheat"] + (["sorghum"] if dt == "dt_sorghum" else []):
            d_, s_, l_ = crop_D(f, c)
            if d_ is not None:
                D[c], src[c], lpa[c] = d_, s_, l_
        if "wheat" not in D:
            continue
        # income inputs
        NRin, ysrc, cost_ok = {}, {}, True
        for c in D:
            Y, ys = yields(f, st_, c)
            Pz, pus = price(st_, c)
            C, rg = cost(st_, c)
            NRin[c] = (Y, Pz, C)
            ysrc[c] = (ys, pus)
        cflags = []  # card-independent county flags
        ctx = {}
        # irrigation: Census of Agriculture share of harvested cropland and RMA insured irrigated share of corn
        irr_c = cs.loc[f, "irrigated_share"] if f in cs.index else np.nan
        corn_irr = _rma_corn_irr_cache().get(f, np.nan)
        vals = [x for x in (irr_c, corn_irr) if x is not None and np.isfinite(x)]
        if vals:
            irr_use = max(vals)
            ctx["irr"] = int(round(100 * irr_use))
            if irr_use >= 0.25:
                cflags.append("irr_high")
            elif irr_use >= 0.10:
                cflags.append("irr_some")
        prcp = _static_feat(f, "clim_prcp_jja_mm")
        edd = _static_feat(f, "clim_edd30_jja")
        aws = cs.loc[f, "aws0_150_mm"] if f in cs.index else np.nan
        if np.isfinite(prcp):
            ctx["prcp"] = int(round(prcp))
            if prcp < 260:
                cflags.append("dry_summer")
        if np.isfinite(edd):
            ctx["edd"] = int(round(edd))
            if edd >= 50:
                cflags.append("hot")
        if np.isfinite(aws):
            ctx["aws"] = int(round(aws))
            if aws < 200:
                cflags.append("low_aws")
        b = bc.get(f, {})
        try:
            e0 = b["expected_bill"]["est"]
            e45 = b["bill_2045"]["ssp245"]["est"]
            if e0 and e45:
                ctx["c45"] = int(round(100 * (e45 / e0 - 1)))
                cflags.append("c45")
        except (KeyError, TypeError):
            pass
        s3p = (b.get("diversity") or {}).get("now")
        if s3p is not None:
            ctx["s3p"] = int(round(100 * s3p))
        if st_ == "KS" or (st_ in ("NE", "SD") and np.isfinite(prcp) and prcp < 260):
            cflags.append("ww_drought")

        rot_out = {}
        for cur, rot in ROTATIONS.items():
            cur_parts = rot["parts"]
            Scur = rot_series(cur_parts, D, R)
            mc, p80c, p90c = stats3(Scur)
            cards = []

            def card(sid, mean, p80, p90, dmean, dp90, inc, flags):
                v = []
                for A in (mean, p80, p90):
                    lo, hi = interval(A, mode)
                    v += trip(A[0, 0], lo, hi)
                for A in (dmean, dp90):
                    if A is None:
                        v += [None, None, None]
                    else:
                        lo, hi = interval(A, mode)
                        v += trip(A[0, 0], lo, hi)
                v += inc if inc is not None else [None, None, None]
                c_ = {"s": sid, "v": v}
                if flags:
                    c_["f"] = flags
                cards.append(c_)

            def crop_flags(crops):
                fl = []
                for c in crops:
                    s_ = src.get(c)
                    if c in ("wheat", "sorghum", "soybeans") and s_ in ("thin",):
                        fl.append(f"{c}_thin")
                    elif s_ in ("pooled", "pooled_us", "pooled_ratio"):
                        fl.append(f"{c}_pooled")
                    ys, pus = ysrc.get(c, ("county", False))
                    if ys != "county":
                        fl.append(f"y_{ys}_{c}")
                    if pus:
                        fl.append(f"p_us_{c}")
                return fl

            cur_crops = sorted({c for c, _, _ in cur_parts})
            card("current", mc, p80c, p90c, None, None, None, crop_flags(cur_crops))
            for sid, tparts in targets(cur, dt).items():
                if sid == "cover_crop":
                    inc_y = {a: rot_income(cur_parts, NRin, a, cover=True) - rot_income(cur_parts, NRin, a)
                             for a in ("est", "lo", "hi")}
                    inc = trip(inc_y["est"].mean(), inc_y["lo"].min(), inc_y["hi"].max())
                    card(sid, mc, p80c, p90c, None, None, inc, [])
                    continue
                # bill: "cs_from_cc" corn gets the scenario like "div"
                bparts = [(c, w, "div" if tag in ("div", "cs_from_cc") else tag) for c, w, tag in tparts]
                if any(c not in D for c, _, _ in bparts):
                    continue
                St = rot_series(bparts, D, R)
                ms, p80s, p90s = stats3(St)
                # income
                iparts = [(c, w, "simple" if tag == "cs_from_cc" else tag) for c, w, tag in tparts]
                inc_y = {}
                for a in ("est", "lo", "hi"):
                    ba = a if sid == "cc_to_cs" else "est"
                    inc_y[a] = rot_income(iparts, NRin, a) - rot_income(cur_parts, NRin, a, beta_a=ba)
                inc = trip(inc_y["est"].mean(), inc_y["lo"].min(), inc_y["hi"].max())
                newc = sorted({c for c, _, _ in tparts} - set(cur_crops))
                card(sid, ms, p80s, p90s, ms - mc, p90s - p90c, inc, crop_flags(newc))
            rot_out[cur] = cards
            for c_ in cards:
                summ_rows.append({"fips": f, "state": st_, "rotation": cur, "strategy": c_["s"],
                                  **{FIELDS[i // 3] + ["_est", "_lo", "_hi"][i % 3]: c_["v"][i] for i in range(18)}})
        counties_out[f] = {"n": cty.loc[f, "name"] if f in cty.index else f, "st": st_, "ctx": ctx,
                           "f": cflags, "rot": rot_out,
                           "src": {c: src[c] for c in src}, "lpa": {c: rnd(lpa[c]) for c in lpa}}
    print(f"cards built for {len(counties_out)} counties ({time.time() - t0:.0f}s)", flush=True)

    # ---- assemble JSON
    meta = strategy_meta(P, div, reg, have_costs, ers_meta, mode)
    doc = {
        "schema": "compact-v1",
        "schema_doc": ("counties[fips].rot[rotation_class] = list of cards {s: strategy_id, v: 18 numbers = "
                       "[est, lo, hi] for each name in `fields` (null = not quantified), f: card flag codes}; "
                       "county-level flag codes in counties[fips].f; flag text templates in `flags` "
                       "({irr},{prcp},{edd},{aws},{c45},{s3p} come from counties[fips].ctx); shared card text "
                       "(name, why, benefits, gaps, risks, evidence) in `strategies`."),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mock": False,
        "units": "USD per acre per year (rotation average over the crops in the rotation)",
        "dollar_year": "2020-2024 nominal (county liability per insured acre 2020-2024; NASS/ERS 2019-2023 for income)",
        "interval_method": ("5th-95th percentile over 100 bootstrap refits of the loss model, combined per draw; for "
                            "scenario cards the envelope over the rotation scenario r = lo..hi"
                            if mode == "bootstrap" else
                            "approximate: per-year 5th/95th bootstrap percentiles from sim_county_crop (comonotone); "
                            "envelope over the rotation scenario r = lo..hi"),
        "income_method": meta.pop("_income_method"),
        "scenario": {"r": app["r"], "label": app["label"], "source": "model/outputs/diversity_effect.json app_effect"},
        "fields": FIELDS,
        "rotations": {k: {"mix": v["mix"]} for k, v in ROTATIONS.items()},
        "strategies": meta.pop("_strategies"),
        "flags": meta.pop("_flags"),
        "counties": counties_out,
    }
    WEB.mkdir(parents=True, exist_ok=True)
    out = WEB / "strategies.json"
    with open(out, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"), allow_nan=False)
    size = out.stat().st_size
    print(f"wrote {out} ({size / 1e6:.2f} MB)")

    # ---- summary
    S = pd.DataFrame(summ_rows)
    summary = {
        "generated_at": doc["generated_at"], "interval_mode": mode, "draws": int(L.shape[0]),
        "file_size_bytes": size, "counties": len(counties_out), "counties_in_sim": len(fips_all),
        "eligible_rule": "corn sim with >= 5 insured years 2001-2024 and a soybean sim row (sim_county_crop)",
        "sorghum_states": sorghum_states,
        "dt_choice": pd.Series({f: plan[f]["dt"] for f in counties_out}).value_counts().to_dict(),
        "crop_source_counts": {c: pd.Series([counties_out[f]["src"].get(c) for f in counties_out]).value_counts().to_dict()
                               for c in ["corn", "soybeans", "wheat", "sorghum"]},
        "synthesised_county_crops": len(synth),
        "ers_costs": {"status": "ok" if have_costs else "unavailable: revenue only",
                      "page": ERS_PAGE, "files": ERS_FILES, "regions_used": {s_: ERS_REGION[s_] for s_ in ERS_REGION},
                      "sorghum_region_note": "sorghum operating costs 2019-2023 only published for Prairie Gateway "
                                             "(and Fruitful Rim); Prairie Gateway used for every state",
                      "operating_cost_2019_2023_mean": {f"{rg}|{c}": round(float(np.mean([costs[(rg, c, y)] for y in INC_YEARS])), 2)
                                                        for (rg, c, y) in costs if y == 2019
                                                        and all((rg, c, yy) in costs for yy in INC_YEARS)}},
        "scenario_r": app["r"],
        "by_state_median": (S.groupby(["state", "rotation", "strategy"])[["expected_bill_est", "delta_bill_est",
                                                                            "delta_income_per_ac_est"]]
                            .median().round(2).reset_index().to_dict(orient="records")),
        "examples": {f: counties_out[f] for f in ["19149", "20169", "20157", "31019"] if f in counties_out},
        "flag_counts": pd.Series([x for f in counties_out for x in counties_out[f]["f"]]).value_counts().to_dict(),
        "runtime_s": round(time.time() - t0, 1),
    }
    with open(OUT / "strategies_summary.json", "w") as fh:
        json.dump(summary, fh, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"done in {time.time() - t0:.0f}s")


# ---------------------------------------------------------------------------------------------- cached lookups
_CACHE = {}


def _rma_corn_irr_cache():
    if "irr" not in _CACHE:
        r = pd.read_parquet(PROC / "rma_county_year.parquet",
                            columns=["fips", "year", "crop", "insured_acres", "irrigated_insured_share"])
        r = r[(r.crop == "corn") & r.year.between(2020, 2024)]
        r = r.assign(ia=r.irrigated_insured_share * r.insured_acres)
        g = r.groupby("fips").agg(ia=("ia", "sum"), a=("insured_acres", "sum"))
        _CACHE["irr"] = (g.ia / g.a.replace(0, np.nan)).to_dict()
    return _CACHE["irr"]


def _static_feat(f, col):
    if "hz" not in _CACHE:
        h = pd.read_parquet(OUT / "hazard_features.parquet")
        cols = [c for c in ["clim_prcp_jja_mm", "clim_edd30_jja"] if c in h.columns]
        _CACHE["hz"] = h.drop_duplicates("fips").set_index("fips")[cols]
    hz = _CACHE["hz"]
    return float(hz.loc[f, col]) if (f in hz.index and col in hz.columns) else np.nan


# ---------------------------------------------------------------------------------------------- text
def strategy_meta(P, div, reg, have_costs, ers_meta, mode):
    r = div["app_effect"]["r"]
    rp = lambda x: f"{round(100 * x)}%"  # noqa: E731
    k22 = P["E5_corn_kluger2022"]["effect"]
    k_shrink = round(100 * (1 - k22["hottest_quintile"] / k22["coolest_quintile"]))
    verdict_short = ("Our county insurance data did not confirm a protective effect of rotation diversity on corn "
                     "drought losses (no robust estimate; see model/outputs/diversity_effect.json)")
    reg_r = reg["region"]["change_2045_pct"]
    gcms = reg["region"].get("gcms_2045", [])
    P_ = lambda pid: P[pid]  # noqa: E731
    eros = P_("E1_erosion_kaspar2001")["effect"]
    infil = P_("E1_infiltration_basche2019")["effect"]["mean"]
    soc = P_("E1_soc_he2025")["effect"]["mean"]
    no3 = P_("E1_nitrate_kaspar2007")["effect"]["mean"]
    pant_c = P_("E1_corn_yield_pantoja")["effect"]["mean"]
    marc = P_("E1_corn_yield_marcillo")["effect"]["mean"]
    dein_c = P_("E1_corn_yield_deines")["effect"]["mean"]
    dein_s = P_("E1_soy_yield_deines")["effect"]["mean"]
    he_us = P_("E1_yield_he2025_us")["effect"]["mean"]
    pant_s = P_("E1_soy_yield_pantoja")["effect"]["mean"]
    dav_c = P_("E4_corn_yield_davis2012")["effect"]["mean"]
    dav_s = P_("E4_soy_yield_davis2012")["effect"]["mean"]
    dav_n = P_("E4_nfert_davis2012")["effect"]["mean"]
    dav_h = P_("E4_herbicide_davis2012")["effect"]["mean"]
    k25d = P_("E4_corn_divers_kluger2025")["effect"]["mean"]
    k25r = P_("E5_corn_kluger2025")["effect"]["mean"]
    ak = P_("E5_corn_alkaisi2015")["effect"]
    seif = P_("E5_corn_seifert2017")["effect"]["mean"]
    src = lambda pid, label: {"label": label, "url": P[pid].get("url")}  # noqa: E731

    S_RMA = {"label": "USDA RMA Cause of Loss + Summary of Business (county drought indemnity, liability)",
             "url": "https://pubfs-rma.fpac.usda.gov/pub/Web_Data_Files/Summary_of_Business/"}
    S_POWER = {"label": "NASA POWER daily weather 1981-2024 (loss-model hazard)", "url": "https://power.larc.nasa.gov/"}
    S_VAL = {"label": "Drought Bill loss model: out-of-time test 2021-2024 (VALIDATION.md)", "url": None}
    S_BOWLES = {"label": "Bowles et al. 2020, One Earth 2:284 (diverse rotations: 14-90% smaller maize drought-year losses)",
                "url": "https://doi.org/10.1016/j.oneear.2020.02.007"}
    S_KLUGER22 = {"label": "Kluger, Owen & Lobell 2022, Environ. Res. Lett. 17:044066 (corn rotation benefit, smaller in hot years)",
                  "url": "https://doi.org/10.1088/1748-9326/ac6083"}
    S_DIV = {"label": "Drought Bill county-data analysis of rotation diversity (no robust effect)", "url": None}
    S_NASS = {"label": "USDA NASS QuickStats county yields and state prices 2019-2023", "url": "https://www.nass.usda.gov/datasets/"}
    S_ERS = {"label": "USDA ERS Commodity Costs and Returns (operating costs by region)", "url": ERS_PAGE}
    S_SARE = {"label": "SARE/CTIC 2012-13 cover crop survey (farmer-reported; via MSU Extension)",
              "url": "https://www.canr.msu.edu/news/survey_shows_improved_corn_and_soybean_yields_when_cover_crops_were_seeded"}
    S_EIB = {"label": "USDA ERS EIB-222 (2021) Cover Crop Trends, Programs, and Practices (seed costs, cost-share)",
             "url": ERS_COVER}

    inc_cost = ("NASS yields x state prices minus USDA ERS operating costs" if have_costs
                else "revenue only, costs not included")
    strategies = [
        {"id": "current", "name": "Keep current rotation", "short": "Current",
         "description": "Your baseline: what your rotation draws from crop insurance for drought, per acre per year.",
         "why": ("Baseline. The county's loss model (trained on 2001-2024 RMA drought claims) is applied to every "
                 "NASA POWER weather year 1981-2024 with today's insured crops; each crop's simulated loss is "
                 "weighted by its share in your rotation, year by year, so bad years add up correctly."),
         "benefits": ["No change in equipment, markets or know-how."],
         "gaps": ["The bill is insured drought loss (RMA cause 'drought') at 2020-2024 coverage and prices; your own "
                  "uninsured loss can be larger.",
                  "Each crop uses the county-average insured loss cost for that crop; field soils and management are "
                  "not observed.",
                  "In the 2021-2024 test the model ranked counties well but under-predicted the 2022 and 2023 regional "
                  "totals by about half (multi-season droughts)."],
         "risks": [f"Climate projections (NEX-GDDP-CMIP6, {len(gcms)} models) raise the regional drought bill by about "
                   f"{round(reg_r['ssp245']['est'])}% (SSP2-4.5) to {round(reg_r['ssp585']['est'])}% (SSP5-8.5) "
                   "around 2045 at today's acres and prices."],
         "evidence": {"grade": "moderate", "sources": [S_RMA, S_POWER, S_VAL]},
         "income_note": None},
        {"id": "cc_to_cs", "name": "Rotate: corn-soybean", "short": "Rotate corn-soy",
         "description": "Grow soybeans every other year; corn follows soybean.",
         "why": (f"Corn after soybean yields more than corn after corn: about {k22['mean']} t/ha "
                 f"(~{round(k22['mean'] * BU_PER_T_HA)} bu/acre) in randomized trials combined with satellite data "
                 f"(Kluger et al. 2022); Iowa trials found continuous corn 11-28% lower (Al-Kaisi et al. 2015). "
                 "The bill change uses the county's soybean loss costs for half the acres. For the corn half it adds "
                 f"a SCENARIO, not an estimate: rotated corn loses {rp(r['est'])} less in drought years (range "
                 f"{rp(r['lo'])}-{rp(r['hi'])}), the same assumption as the diversity slider (Bowles et al. 2020)."),
         "scenario": True,
         "benefits": ["Higher corn yield after soybean (the rotation benefit).",
                      "Corn after soybean needs less nitrogen fertilizer than corn after corn.",
                      "Breaks the corn rootworm cycle."],
         "gaps": ["No trial isolates corn-soybean vs continuous corn in drought years: the drought part is a scenario.",
                  "ERS operating costs are not split by rotation; continuous corn usually needs more nitrogen, so the "
                  "income gain is likely understated.",
                  "Insured corn in a county mixes rotations; the continuous-corn bill uses the county average and "
                  "probably understates continuous-corn losses."],
         "risks": [f"The corn rotation benefit is about {k_shrink}% smaller in the hottest years than in the coolest "
                   "(Kluger et al. 2022).",
                   "Soybean drought losses (August pod fill) remain; soybean markets and prices."],
         "evidence": {"grade": "strong", "sources": [S_KLUGER22, src("E5_corn_alkaisi2015", "Al-Kaisi et al. 2015, Agron. J. (Iowa rotation trials)"),
                                                     src("E5_corn_seifert2017", "Seifert, Roberts & Lobell 2017, Agron. J. (750k fields)"),
                                                     S_BOWLES, S_RMA]},
         "income_note": (f"{inc_cost}. Continuous-corn yield = county yield minus the rotation benefit: "
                         f"{k22['mean']} t/ha (Kluger 2022; range {k25r}% net, Kluger 2025, to {ak['mean']}% of CC yield, "
                         "Al-Kaisi 2015).")},
        {"id": "cs_small_grain", "name": "Add a small grain: corn-soybean-wheat", "short": "Add small grain",
         "description": "A 3-year rotation: 1/3 corn, 1/3 soybeans, 1/3 wheat (or another small grain).",
         "why": ("Spreads drought risk across seasons: wheat grows in fall and spring and is harvested by early summer, "
                 "before the July-August heat that drives corn and soybean drought losses. The bill change combines "
                 "the county's own simulated wheat loss costs for a third of the acres with a TRIAL-BASED SCENARIO for "
                 f"corn: corn in a 3+ crop rotation loses {rp(r['est'])} less in drought years (range "
                 f"{rp(r['lo'])}-{rp(r['hi'])}; Bowles et al. 2020 found 14-90% across 11 long-term trials). "
                 f"{verdict_short}."),
         "scenario": True,
         "benefits": [f"In the Iowa Marsden Farm trial (Davis et al. 2012), 3- and 4-year rotations had {dav_c:g}% higher "
                      f"corn and {dav_s:g}% higher soybean yields than corn-soybean, with {abs(dav_n):g}% less manufactured "
                      f"nitrogen and {abs(dav_h):g}% less herbicide.",
                      "A crop that is harvested in early summer avoids the corn silking window.",
                      "Breaks corn-soybean pest and weed cycles."],
         "gaps": [f"{verdict_short}: the drought benefit shown is the trial range, not a local estimate.",
                  "Bowles et al. had no Iowa site; the closest analog (Minnesota, corn-soy vs corn-soy-oat/alfalfa) "
                  "showed no significant drought-year benefit.",
                  f"A national satellite study found {k25d:g}% corn yield for 3-year vs corn-soybean rotations "
                  "(Kluger et al. 2025, observational).",
                  "Wheat loss costs come from a May-August weather model; fall-to-spring droughts that hurt winter "
                  "wheat (e.g. Kansas 2023) are under-predicted, so wheat losses are likely understated."],
         "risks": [f"Rotation benefits for corn shrink in the hottest years (about {k_shrink}% smaller in the hottest vs "
                   "coolest temperature quintile, Kluger et al. 2022).",
                   "Needs a local market for wheat or oats, and equipment and know-how for a third crop.",
                   "Wheat usually earns less per acre than corn: check the income line."],
         "evidence": {"grade": "moderate", "sources": [S_BOWLES, S_DIV, S_KLUGER22,
                                                       src("E4_corn_yield_davis2012", "Davis et al. 2012, PLoS ONE (Marsden Farm, Iowa)"),
                                                       src("E4_corn_divers_kluger2025", "Kluger, Di Tommaso & Lobell 2025, Environ. Res. Lett."),
                                                       S_RMA]},
         "income_note": (f"{inc_cost}. Rotation yield effect: central 0; range {k25d:g}% corn (Kluger 2025) to "
                         f"+{dav_c:g}% corn / +{dav_s:g}% soybean (Davis 2012).")},
        {"id": "cover_crop", "name": "Cereal rye cover crop", "short": "Rye cover crop",
         "description": "Plant cereal rye after harvest; terminate it before the next crop.",
         "why": ("Living roots over winter protect the soil and can improve infiltration and soil organic matter. Its "
                 "effect on drought losses is NOT quantified, so the bill is shown unchanged: drought-year evidence is a "
                 "farmer survey (SARE/CTIC 2012: corn +9.6%, soybean +11.6% after cover crops, self-reported), while "
                 f"controlled studies show no average corn yield change with grass covers (Marcillo & Miguez 2017: {marc:g}%) "
                 f"and {pant_c:g}% corn after rye in Iowa trials (Pantoja et al. 2015)."),
         "not_quantified": "Drought-bill effect not quantified: no controlled evidence on drought-year losses.",
         "benefits": [f"Cuts interrill erosion about {abs(eros['mean']):g}% and rill erosion about {abs(eros['rill_erosion_pct']):g}% "
                      "vs no-till without a cover (Kaspar et al. 2001, central Iowa).",
                      f"Raises water infiltration about {infil:g}% on average (Basche & DeLonge 2019 meta-analysis).",
                      f"Raises soil organic carbon about {soc:g}% with non-legume covers (He et al. 2025).",
                      f"Cuts tile-drainage nitrate load about {abs(no3):g}% (Kaspar et al. 2007, central Iowa).",
                      "Cost-share exists: in 2018 federal and state cover-crop payments ranged from $12 to $92 per acre "
                      "(USDA ERS EIB-222); some years add a $5/acre crop-insurance premium discount."],
         "gaps": ["No controlled study isolates cover-crop effects on drought-year insured losses.",
                  "The drought-year yield gains are self-reported (SARE/CTIC survey, >750 farmers), not a trial.",
                  f"Income line = trial yield effects (corn {pant_c:g}% to {marc:g}%, soybean {he_us:g}% to +{pant_s:g}%) "
                  "minus rye seed ($14-16/acre, USDA ERS); seeding, termination passes and cost-share are not included."],
         "risks": ["In dry areas a cover crop can use spring soil water the next crop needs: in the Central Great Plains "
                   "wheat after cover crops yielded ~10% less than after fallow, more in dry years (Nielsen et al. 2016).",
                   "Terminate early before corn in a dry spring; late termination can cut corn yield.",
                   f"Fields with 3+ years of cover crops had {dein_c:g}% corn and {dein_s:g}% soybean yield in a satellite "
                   "study (Deines et al. 2023), larger after dry springs."],
         "evidence": {"grade": "thin", "sources": [S_SARE,
                                                   src("E1_corn_yield_marcillo", "Marcillo & Miguez 2017, J. Soil Water Conserv. (meta-analysis)"),
                                                   src("E1_corn_yield_pantoja", "Pantoja et al. 2015, SSSAJ (Iowa rye trials)"),
                                                   src("E1_erosion_kaspar2001", "Kaspar et al. 2001 (erosion; ISU PM 1999)"),
                                                   src("E1_infiltration_basche2019", "Basche & DeLonge 2019 (infiltration meta-analysis)"),
                                                   src("E1_soc_he2025", "He et al. 2025, npj Sustain. Agric."),
                                                   src("E1_corn_yield_deines", "Deines et al. 2023, Global Change Biology"),
                                                   S_EIB]},
         "income_note": "yield effects and rye seed cost only (seeding/termination not included)"},
        {"id": "dt_sorghum", "name": "Swap corn for grain sorghum", "short": "Sorghum swap",
         "description": "Grow grain sorghum in the corn years (e.g. sorghum-soybean).",
         "why": ("Sorghum tolerates heat and dry spells better than corn and uses less water: in a 2009-2011 Nebraska "
                 "rainfed trial it used over 2 inches less water than corn or soybean (UNL CropWatch); K-State reports a "
                 "yield advantage over corn where yields are below about 80 bu/acre. The bill uses this county's "
                 "simulated sorghum loss costs and sorghum liability per acre (state-pooled where flagged)."),
         "benefits": ["Lower seed and fertilizer costs than corn (USDA ERS operating costs).",
                      "Better water-use efficiency and heat tolerance in dryland, lower-yield fields."],
         "gaps": ["Part of any bill change comes from lower liability per acre (less insured value), not only fewer losses.",
                  "Where much of the corn is irrigated, insured sorghum is mostly dryland, so the swap can even raise "
                  "the county-average bill: compare like with like on your own fields.",
                  "Sorghum insurance history is short in many counties; flagged counties use pooled estimates.",
                  "Sorghum operating costs for 2019-2023 are published only for the Prairie Gateway region; used for "
                  "every state."],
         "risks": ["Corn has the higher yield ceiling: where water is ample corn usually earns more.",
                   "Local elevator access and price basis for sorghum.",
                   "Different pests (e.g. sugarcane aphid, birds) and fewer herbicide options than corn."],
         "evidence": {"grade": "moderate", "sources": [S_RMA, {"label": "UNL CropWatch, sorghum water use (Rees 2013; reported, not opened)", "url": None},
                                                       {"label": "K-State Agricultural Experiment Station sorghum vs corn reports (reported, not opened)", "url": None},
                                                       S_NASS, S_ERS]},
         "income_note": f"{inc_cost} (sorghum costs: Prairie Gateway)."},
        {"id": "dt_wheat", "name": "Swap corn for wheat", "short": "Wheat swap",
         "description": "Grow wheat in the corn years (e.g. wheat-soybean, often with double-crop soybeans).",
         "why": ("Where sorghum is not an established insured crop, wheat is the drought-escape option: it grows in fall "
                 "and spring and is harvested by early summer, before the July-August heat that drives most corn drought "
                 "losses. The bill uses the county's simulated wheat loss costs and wheat liability per acre."),
         "benefits": ["Harvest in early summer avoids the corn silking window.",
                      "Opens a summer window for double-crop soybeans or a cover/forage where rain allows."],
         "gaps": ["Wheat loss costs come from a May-August weather model; fall-to-spring droughts are under-predicted "
                  "(2023 regional wheat test: $0.23B predicted vs $0.75B actual).",
                  "Part of the lower bill comes from lower liability per acre (less insured value)."],
         "risks": ["Wheat usually earns much less per acre than corn here: check the income line.",
                   "Winter-kill, head scab in wet springs, and local market access."],
         "evidence": {"grade": "moderate", "sources": [S_RMA, S_VAL, S_NASS, S_ERS]},
         "income_note": inc_cost + "."},
    ]
    flags = {
        "irr_high": "About {irr}% of cropland here is irrigated. Insured drought losses here are mostly on dryland "
                    "acres: a dryland field likely faces a higher bill than this county average, an irrigated field a "
                    "much lower one. Yields and loss costs are county averages that mix irrigated and dryland fields "
                    "(insured sorghum and wheat are mostly dryland, corn often irrigated).",
        "irr_some": "About {irr}% of cropland here is irrigated; the county average mixes dryland and irrigated acres.",
        "dry_summer": "Dry summers (June-August rain about {prcp} mm, NASA POWER 1991-2020): a cover crop's spring "
                      "water use is a real risk here; plan early termination.",
        "hot": "Hot summers (about {edd} degree-days above 30 C in June-August, NASA POWER 1991-2020): corn rotation "
               "benefits shrink in the hottest years.",
        "low_aws": "Soils here hold little plant-available water (about {aws} mm in the top 150 cm, SSURGO); drought "
                   "stress builds fast. Check your own field's soils.",
        "ww_drought": "Winter wheat here is exposed to fall-to-spring drought that the May-August weather model does "
                      "not see; wheat loss costs are likely understated.",
        "c45": "Climate projections put this county's drought bill about {c45}% higher around 2045 (SSP2-4.5, "
               "NEX-GDDP-CMIP6, today's acres and prices).",
        "wheat_thin": "Few years of insured wheat in this county: its wheat loss cost leans on state/region patterns.",
        "wheat_pooled": "No insured wheat here in 2020-2024: the wheat loss cost is a pooled model estimate and the "
                        "liability per acre is the state's (the US average where the state insures under 10,000 "
                        "wheat acres, e.g. Iowa, where the usual small grain is oats).",
        "sorghum_thin": "Few years of insured sorghum in this county: its sorghum loss cost leans on state/region patterns.",
        "sorghum_pooled": "No insured sorghum here in 2020-2024: sorghum loss cost and liability per acre are "
                          "state-pooled model estimates.",
        "soybeans_thin": "Few years of insured soybeans here: the soybean loss cost leans on state/region patterns.",
        "y_state_wheat": "County wheat yields are not published by NASS for most of 2019-2023: state yields used.",
        "y_state_sorghum": "County sorghum yields are not published for most of 2019-2023: state yields used.",
        "y_state_soybeans": "County soybean yields are not published by NASS for most of 2019-2023: state yields used.",
        "y_state_corn": "County corn yields are not published by NASS for most of 2019-2023: state yields used.",
        "y_region_wheat": "No NASS wheat yield for this state in 2019-2023: mean of the other Heartland states used.",
        "y_region_sorghum": "No NASS sorghum yield for this state: mean of neighbouring states in its ERS region used.",
        "y_US_wheat": "No state wheat yield: US average used.",
        "y_US_sorghum": "No state sorghum yield: US average used.",
        "p_us_sorghum": "No state sorghum price for most of 2019-2023: US price used.",
        "p_us_wheat": "No state wheat price for most of 2019-2023: US price used.",
    }
    # county-level flags apply only to some cards; card-level flags (crop sources) apply to the card carrying them
    applies = {"irr_high": ["current", "cover_crop", "dt_sorghum", "dt_wheat"], "irr_some": ["current"],
               "dry_summer": ["cover_crop"], "hot": ["cs_small_grain", "cc_to_cs"],
               "low_aws": ["current", "cover_crop"], "ww_drought": ["cs_small_grain", "dt_wheat", "current"],
               "c45": ["current"]}
    flags = {k: {"text": v, "cards": applies.get(k)} for k, v in flags.items()}
    income_method = (
        "delta_income_per_ac = change in net return vs the current rotation, $/acre/yr: NASS county yield (2019-2023 "
        "each year; state, then same-ERS-region states, then US when suppressed) x NASS state marketing-year price "
        "(US when missing) minus USDA ERS Commodity Costs and Returns 'Total, operating costs' per planted acre "
        "(region: IA/IL/MN/MO Heartland, KS/NE Prairie Gateway, SD Northern Great Plains; sorghum Prairie Gateway); "
        "est = mean of the 5 yearly deltas, lo/hi = min/max over the years under the low/high rotation-yield "
        "assumptions. Excludes insurance premiums and indemnities, land, machinery and overhead."
        if have_costs else
        "revenue only, costs not included (USDA ERS cost files could not be fetched)")
    return {"_strategies": strategies, "_flags": flags, "_income_method": income_method}


if __name__ == "__main__":
    main()
