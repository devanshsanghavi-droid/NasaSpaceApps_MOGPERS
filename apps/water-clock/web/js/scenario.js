// Client-side clock arithmetic. Every input comes from web/data/*.json; this module only
// combines them. The formulas are documented in notes/frontend.md.
import { num, lo, hi, isNum, CAP } from './util.js';

const thrKey = t => String(t);

// --- Threshold handling -------------------------------------------------------------
// Years left at threshold T for a field. fields.json gives y10/y50/y90 at the default 30 ft
// threshold and y10_15..y90_50 from the same Monte Carlo at 15 and 50 ft. Older files without
// those columns fall back to scaling by (sat - T)/(sat - 30), never keeping a capped 100+ at a
// stricter threshold when thickness and decline say fewer years.
export function fieldYears(f, thr, defThr = 30) {
  const sat = f.sat_ft, decl = f.decl;
  const base = { p10: f.y10, p50: f.y50, p90: f.y90 };
  if (thr === defThr) return { ...base, below: isNum(sat) && sat <= thr };
  if (!isNum(sat)) return { p10: null, p50: null, p90: null, below: false };
  const k = thrKey(thr);
  if (isNum(f['y50_' + k])) {
    return { p10: num(f['y10_' + k]), p50: num(f['y50_' + k]), p90: num(f['y90_' + k]), below: sat <= thr };
  }
  const availT = sat - thr, availD = sat - defThr;
  if (availT <= 0) return { p10: 0, p50: 0, p90: 0, below: true };
  if (availD > 0) {
    const r = availT / availD;
    const sc = (v, isLow) => {
      if (!isNum(v)) return null;
      if (v >= CAP) return r < 1 && isNum(decl) && decl > 0 ? Math.min(CAP, availT / decl) : CAP;
      if (v <= 0 && r > 1) return isLow ? null : 0; // unknown how far below the default threshold
      return Math.min(CAP, v * r);
    };
    return { p10: sc(base.p10, true), p50: sc(base.p50), p90: sc(base.p90), below: false };
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
// share: capped at 1 (proportional response, the conservative reading).
// raw: the uncapped water-balance ratio; raw > 1 means pumping alone would cause more decline than
// is observed (net inflow from recharge, return flow or lateral flow), so the decline should respond
// more than proportionally to a pumping cut. Used for the high end of every gain range.
export function pumpingShare(D, fips) {
  const s = D.scenByFips[fips];
  const d = num(s?.decline_ft_yr), dp = num(s?.decline_from_pumping_ft_yr);
  let share = null;
  if (isNum(s?.pumping_share)) share = Math.max(0, Math.min(1, s.pumping_share));
  else if (isNum(d) && d > 0 && isNum(dp)) share = Math.max(0, Math.min(1, dp / d));
  if (!isNum(share)) return { share: 1, raw: 1, assumed: true, capped: false };
  const raw = isNum(s?.pumping_share_raw) ? Math.max(share, s.pumping_share_raw) : share;
  return { share, raw, assumed: false, capped: raw > share + 1e-6 };
}

// Years gained at a field if the field and all irrigated land around it (drawing on the same
// aquifer) switch from S0 to strategy sid. Years Y = avail/decline; the pumping part of the decline
// scales with pumping (1 + p): Y_new = Y / (1 + share*p).
//   est = proportional reading (capped share) with the central pumping change;
//   lo  = proportional reading with the smallest pumping cut;
//   hi  = net-inflow reading (uncapped share) with the largest pumping cut.
// Computed at Y = p50 only, so the range is not an artefact of the 100-year cap.
export function yearsGained(D, fips, sid, years) {
  if (sid === 'S0') return { est: 0, lo: 0, hi: 0, note: null };
  if (!years || years.below || !isNum(years.p50) || years.p50 <= 0) return null;
  const p = pumpingChange(D, fips, sid);
  if (!p) return null;
  const { share, raw } = pumpingShare(D, fips);
  const Y = years.p50;
  if (Y >= CAP) return { est: 0, lo: 0, hi: 0, atCap: true };
  const g = (pp, sh) => {
    const f = 1 + sh * pp;
    const yNew = f <= 0.0001 ? CAP : Math.min(CAP, Y / f);
    return yNew - Y;
  };
  const est = g(p.est, share);
  const lo = Math.min(est, g(p.hi, share));
  const hi = Math.max(est, g(p.lo, raw), g(p.est, raw));
  return { est, lo, hi, capped: Y + est >= CAP - 1e-9, hiCapped: Y + hi >= CAP - 1e-9 };
}

// --- Community slider ----------------------------------------------------------------
// "If X% of irrigated corn in county shifts to strategy sid, the county clock gains Z years."
//   saved_af      = X * irrigated_corn_acres * (net_S0 - net_sid) / 12      [AF/yr]
//   new_decline   = decline - decline_from_pumping * saved_af / pumping_af_yr   (proportional, conservative)
//   high end      = same with decline_from_pumping_ft_yr_net_inflow (uncapped pumping share)
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
  const dPumpHi = Math.max(isNum(dPump) ? dPump : 0, num(s.decline_from_pumping_ft_yr_net_inflow) ?? 0);
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

  // net-inflow reading: the uncapped pumping share (see pumpingShare); same water saved
  const dDeclHi = how === 'pumping share' && dPumpHi > 0 ? dPumpHi * savedAf / pump : dDecl;
  const yearsAt = d => (d <= 0 ? CAP : Math.min(CAP, Math.max(0, avail) / d));
  const one = (d, dd) => {
    if (!isNum(d) || d <= 0) return { before: CAP, after: CAP, gain: 0 };
    const nd = d - dd * (isNum(decl) && decl > 0 ? d / decl : 1); // scale with decline draw
    const b = yearsAt(d), a = yearsAt(nd);
    return { before: b, after: a, gain: a - b };
  };
  const mid = one(decl, dDecl);
  const hiR = one(decl, dDeclHi);
  const alt = [one(declLo, dDecl), one(declHi, dDecl)].map(r => r.gain);
  return {
    savedAf, before: mid.before, after: mid.after, gain: mid.gain,
    gainLo: Math.min(mid.gain, ...alt), gainHi: Math.max(mid.gain, ...alt),
    gainNetInflow: hiR.gain, afterNetInflow: hiR.after, newDeclineNetInflow: Math.max(0, decl - dDeclHi),
    newDecline: Math.max(0, decl - dDecl), decline: decl, how, risingAlready: decl <= 0,
    cornShare: isNum(corn) && isNum(irrAc) && irrAc > 0 ? corn / irrAc : null,
  };
}
