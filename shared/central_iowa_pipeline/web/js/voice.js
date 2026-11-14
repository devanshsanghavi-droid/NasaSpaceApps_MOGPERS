// "Listen": a spoken summary assembled ONLY from values in the loaded JSON. No free text is generated.
import { isNum, fmtInt, BADGE_LABEL } from "./util.js";
import { OUTCOMES, rankStrategies, transportFraction, transportEffect } from "./model.js";
import { typeLabel, strategyName } from "./panel.js";

const SCEN = { ssp245: "S S P 2 4.5", ssp585: "S S P 5 8.5" };

function say(v, nd = 1) {
  if (!isNum(v)) return "unknown";
  const s = Math.abs(v).toFixed(nd);
  if (Number(s) === 0) return "zero";
  return (v < 0 ? "minus " : "plus ") + s;
}

export function buildSummary(app, fieldId) {
  const f = app.fields.get(fieldId);
  if (!f) return "";
  const parts = [];
  if (Object.values(app.source).includes("mock")) parts.push("Warning: this page is showing mock data. These numbers are not real.");
  parts.push(`Field sample ${f.field_id.replace(/^f/, "")}${f.county ? `, ${f.county} County` : ""}.`);
  parts.push(`Field type: ${typeLabel(app, f.type_id)}.`);
  const nType = app.types.get(f.type_id)?.n_fields;
  if (isNum(nType)) parts.push(`There are ${fmtInt(nType)} fields of this type in the region.`);
  const typeEff = app.effects?.by_type?.[f.type_id];
  if (typeEff) {
    const top = rankStrategies(typeEff, app.weights, app.scales).filter((s) => s !== "S0")[0];
    const s = typeEff[top];
    if (s) {
      parts.push(`Top option${app.pref.answers.length ? " for your priorities" : ""}: ${strategyName(app, top)}.`);
      for (const o of OUTCOMES.slice(0, 3)) {
        const oc = s.outcomes?.[o.key];
        if (oc && isNum(oc.lo) && isNum(oc.hi)) parts.push(`${o.label} change between ${say(oc.lo, o.nd)} and ${say(oc.hi, o.nd)} ${o.speak}.`);
      }
      const ev = s.evidence || {};
      const evBits = [];
      if (isNum(ev.n_twin_fields)) evBits.push(`${fmtInt(ev.n_twin_fields)} twin fields`);
      if (isNum(ev.n_trials)) evBits.push(`${fmtInt(ev.n_trials)} randomized trials`);
      parts.push(`Evidence is ${(BADGE_LABEL[s.badge] || s.badge || "unrated").toLowerCase()}${evBits.length ? `, from ${evBits.join(" and ")}` : ""}.`);
      const cal = app.calibration?.[s.badge];
      if (cal && isNum(cal.empirical_error_rate)) parts.push(`Estimates with this badge were wrong ${Math.round(cal.empirical_error_rate * 100)} percent of the time in testing.`);
      if (app.year > 2025) {
        const clim = s.climate?.[app.scenario];
        const moved = transportEffect(s.outcomes?.yield_pct, clim, transportFraction(app.climate, app.scenario, app.year).f);
        if (moved?.beyond) parts.push(`In ${app.year} under ${SCEN[app.scenario]}, this is beyond the evidence. A strip trial is recommended.`);
        else if (moved && isNum(moved.lo) && isNum(moved.hi)) parts.push(`In ${app.year} under ${SCEN[app.scenario]}, the yield change moves to between ${say(moved.lo)} and ${say(moved.hi)} percent.`);
      }
      if (s.failure_box) parts.push(`When it fails: ${s.failure_box}`);
    }
  }
  const sp = app.signpost;
  if (sp && isNum(sp.percentile)) parts.push(`Signpost: ${sp.variable || "the watched variable"} is at the ${Math.round(sp.percentile)}th percentile. ${sp.triggered ? "The signpost is triggered." : "No action needed."}`);
  parts.push("This is decision support, not a replacement for your agronomist.");
  return parts.join(" ");
}

export function speak(app, button) {
  if (!("speechSynthesis" in window) || !app.selected) return;
  const synth = window.speechSynthesis;
  if (synth.speaking) { synth.cancel(); if (button) button.textContent = "Listen"; return; }
  const u = new SpeechSynthesisUtterance(buildSummary(app, app.selected));
  u.lang = "en-US";
  u.rate = 1.0;
  u.onend = u.onerror = () => { if (button) button.textContent = "Listen"; };
  if (button) button.textContent = "Stop";
  synth.speak(u);
}
