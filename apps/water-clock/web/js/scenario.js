// Client-side clock arithmetic. Every input comes from web/data/*.json; this module only
// combines them. The formulas are documented in notes/frontend.md.
import { num, lo, hi, isNum, CAP } from './util.js';

const thrKey = t => String(t);

// --- Threshold handling -------------------------------------------------------------
// Years left at threshold T for a field. fields.json gives y10/y50/y90 at the default 30 ft
// threshold plus sat_ft (saturated thickness) and decl (decline ft/yr). Since
// years = (sat - T) / decline, the years at another threshold scale by (sat - T)/(sat - 30).
export function fieldYears(f, thr, defThr = 30) {
  const sat = f.sat_ft, decl = f.decl;
  const base = { p10: f.y10, p50: f.y50, p90: f.y90 };
  if (thr === defThr) return { ...base, below: isNum(sat) && sat <= thr };
  if (!isNum(sat)) return { p10: null, p50: null, p90: null, below: false };
  const availT = sat - thr, availD = sat - defThr;
  if (availT <= 0) return { p10: 0, p50: 0, p90: 0, below: true };
  if (availD > 0) {
    const k = availT / availD;
    const sc = v => (isNum(v) ? (v >= CAP ? CAP : Math.min(CAP, v * k)) : null);
    return { p10: sc(base.p10), p50: sc(base.p50), p90: sc(base.p90), below: false };
  }
  // Already below the default threshold but above T: only a point estimate is possible.
  if (isNum(decl) && decl > 0) {
    const y = Math.min(CAP, availT / decl);
    return { p10: null, p50: y, p90: null, below: false };
  }
  return { p10: CAP, p50: CAP, p90: CAP, below: false };
}

// Optional D: lets the scenario.json "median_below_threshold" flag mark counties whose typical
// irrigated acre is already thinner than the threshold (p50 = 0 there means "already below").
export function countyYears(c, thr, D = null) {
  const y = c?.years_left?.[thrKey(thr)];
  const flag = D && c?.fips ? D.scenByFips?.[c.fips]?.median_below_threshold?.[thrKey(thr)] : undefined;
  const satMid = num(c?.sat_thick_ft);
  const below = flag === true || (flag === undefined && isNum(satMid) && satMid <= thr);
  if (y) return { p10: num(y.p10), p50: num(y.p50), p90: num(y.p90), below };
  return { p10: null, p50: null, p90: null, below };
}

// Is strategy s assessed for this county? strategies.json may restrict a strategy to a list of
// counties (s.counties) and per_county may lack an entry for it.
export function strategyApplies(D, fips, s) {
  if (!s) return false;
  if (s.id === 'S0') return true;
  if (Array.isArray(s.counties) && fips && !s.counties.map(String).includes(String(fips))) return false;
  const pcAll = D.strategies?.per_county;
  if (pcAll && fips && pcAll[fips] && !pcAll[fips][s.id]) return false;
  return true;
}

// --- Strategy -> pumping change ------------------------------------------------------
// Fractional change in net pumping vs the current strategy S0 (negative = less pumping).
// Prefer the county-specific net pumping from strategies.per_county; else the strategy's
// pumping_change_pct {est,lo,hi}.
export function pumpingChange(D, fips, sid) {
  const pc = D.strategies?.per_county?.[fips];
  const s = D.strategyList.find(x => x.id === sid);
  const pct = s?.pumping_change_pct;
  let est = null, a = null, b = null;
  if (isNum(num(pct))) { est = num(pct) / 100; a = lo(pct) / 100; b = hi(pct) / 100; }
  const n0 = num(pc?.S0?.net_pumping_in_ac), nk = num(pc?.[sid]?.net_pumping_in_ac);
  const regionLess = isNum(est) && est < 0; // the strategy saves water at region level
  if (isNum(n0) && n0 > 0 && isNum(nk)) {
    const local = (nk - n0) / n0;
    // scale the strategy-level spread proportionally around the county estimate
    if (isNum(est) && Math.abs(est) > 1e-9 && isNum(a) && isNum(b)) { a = local * (a / est); b = local * (b / est); }
    else { a = local; b = local; }
    est = local;
  }
  if (!isNum(est)) return null;
  if (!isNum(a)) a = est;
  if (!isNum(b)) b = est;
  const clamp = v => Math.max(-1, v);
  let L = clamp(Math.min(a, b)), H = clamp(Math.max(a, b));
  // a water-saving plan never shows more pumping than today
  if (regionLess || est < 0) H = Math.min(0, H);
  return { est: clamp(est), lo: L, hi: Math.max(L, H) };
}

// Share of the local decline that is caused by pumping (rest = regional/background).
// upperBound: the share was capped at 1 by the model, or the aquifer-mean decline is not
// positive so a ratio is undefined; then "all from pumping" is an upper bound, not an estimate.
export function pumpingShare(D, fips) {
  const s = D.scenByFips[fips];
  const d = num(s?.decline_ft_yr), dp = num(s?.decline_from_pumping_ft_yr);
  let share = null;
  if (isNum(s?.pumping_share)) share = Math.max(0, Math.min(1, s.pumping_share));
  else if (isNum(d) && d > 0 && isNum(dp)) share = Math.max(0, Math.min(1, dp / d));
  if (!isNum(share)) return { share: 1, assumed: true, upperBound: true };
  const mean = num(s?.decline_aquifer_mean_ft_yr);
  const upperBound = share >= 0.999 && (s?.pumping_share_capped === true || (isNum(mean) && mean <= 0));
  return { share, assumed: false, upperBound };
}

// Years gained at a field if the field (and its neighbours drawing on the same aquifer)
// switch from S0 to strategy sid. With years Y = avail/decline and the pumping part of the
// decline scaled by (1 + p): Y_new = Y / (1 + share*p). Range: all combinations of
// Y in {p10,p50,p90} and p in {lo,est,hi}.
export function yearsGained(D, fips, sid, years) {
  if (sid === 'S0') return { est: 0, lo: 0, hi: 0, note: null };
  const p = pumpingChange(D, fips, sid);
  if (!p) return null;
  const { share } = pumpingShare(D, fips);
  const g = (Y, pp) => {
    if (!isNum(Y)) return null;
    if (Y >= CAP) return 0; // already 100+ years; nothing to gain on the capped scale
    const f = 1 + share * pp;
    const yNew = f <= 0.0001 ? CAP : Math.min(CAP, Y / f);
    return yNew - Y;
  };
  const est = g(years.p50, p.est);
  if (!isNum(est)) return null;
  const vals = [];
  for (const Y of [years.p10, years.p50, years.p90]) for (const pp of [p.lo, p.est, p.hi]) { const v = g(Y, pp); if (isNum(v)) vals.push(v); }
  return { est, lo: Math.min(...vals), hi: Math.max(...vals), capped: est > 0 && years.p50 / (1 + share * p.est) >= CAP };
}

// --- Community slider ----------------------------------------------------------------
// "If X% of irrigated corn in county shifts to strategy sid, the county clock gains Z years."
//   saved_af      = X * irrigated_corn_acres * (net_S0 - net_sid) / 12      [AF/yr]
//   new_decline   = decline - decline_from_pumping * saved_af / pumping_af_yr
//     (fallback when pumping_af_yr is missing: decline - ft_per_af_ac * saved_af / irrigated_acres)
//   years         = sat_avail_ft[T] / decline, capped at 100
//   Z             = years(new_decline) - years(decline)
export function countyShift(D, fips, sid, x, thr) {
  const s = D.scenByFips[fips];
  if (!s) return { error: 'No scenario inputs for this county.' };
  const availRaw = s.sat_avail_ft;
  const avail = num(availRaw && typeof availRaw === 'object' && !('est' in availRaw) && !('p50' in availRaw) ? availRaw[thrKey(thr)] : availRaw);
  const decl = num(s.decline_ft_yr), declLo = lo(s.decline_ft_yr), declHi = hi(s.decline_ft_yr);
  const dPump = num(s.decline_from_pumping_ft_yr);
  const corn = num(s.irrigated_corn_acres), pump = num(s.pumping_af_yr), irrAc = num(s.irrigated_acres);
  const ftPer = num(s.ft_per_af_ac);
  const pc = D.strategies?.per_county?.[fips];
  const strat = id => D.strategyList.find(z => z.id === id);
  if (!strategyApplies(D, fips, strat(sid))) return { error: 'This plan is not assessed for this county.' };
  if (s.median_below_threshold?.[thrKey(thr)] === true) {
    return { below: true, note: s.median_below_threshold_note?.[thrKey(thr)] || `The typical irrigated acre here is already below ${thr} ft of water-bearing layer, so this threshold cannot show a gain.` };
  }
  const usePc = !!(pc && pc.S0);
  const net0 = usePc ? num(pc.S0.net_pumping_in_ac) : num(strat('S0')?.water_in_ac);
  const netK = usePc ? num(pc?.[sid]?.net_pumping_in_ac) : num(strat(sid)?.water_in_ac);
  const missingIn = [];
  if (!isNum(avail)) missingIn.push('usable saturated thickness');
  if (!isNum(decl)) missingIn.push('decline rate');
  if (!isNum(corn)) missingIn.push('irrigated corn acres');
  if (!isNum(net0) || !isNum(netK)) missingIn.push('strategy water use');
  if (missingIn.length) return { error: 'Missing ' + missingIn.join(', ') + ' for this county.' };

  if (netK > net0) return { error: 'This plan would not use less water than corn in this county.' };
  const savedAf = Math.max(0, x * corn * (net0 - netK) / 12);
  let dDecl = null, how = '';
  if (isNum(dPump) && isNum(pump) && pump > 0) { dDecl = dPump * savedAf / pump; how = 'pumping share'; }
  else if (isNum(ftPer) && isNum(irrAc) && irrAc > 0) { dDecl = ftPer * savedAf / irrAc; how = 'response coefficient'; }
  else return { error: 'Missing pumping inputs (pumping_af_yr or ft_per_af_ac) for this county.' };

  const yearsAt = d => (d <= 0 ? CAP : Math.min(CAP, Math.max(0, avail) / d));
  const one = d => {
    if (!isNum(d) || d <= 0) return { before: CAP, after: CAP, gain: 0 };
    const nd = d - dDecl * (isNum(decl) && decl > 0 ? d / decl : 1); // scale with decline draw
    const b = yearsAt(d), a = yearsAt(nd);
    return { before: b, after: a, gain: a - b };
  };
  const mid = one(decl);
  const alt = [one(declLo), one(declHi)].map(r => r.gain);
  return {
    savedAf, before: mid.before, after: mid.after, gain: mid.gain,
    gainLo: Math.min(mid.gain, ...alt), gainHi: Math.max(mid.gain, ...alt),
    newDecline: decl - dDecl, decline: decl, how, risingAlready: decl <= 0,
  };
}
