// Playwright QA: loads each view at 1280, 768 and 375 px, switches the replay year, moves the sliders, picks fields
// (sample buttons, keyboard search, map click, deep links), switches tabs; asserts no console errors/warnings, no
// failed requests, no MOCK banner or chips (all data real), no horizontal scroll, no "NaN"/"undefined"/"null" in the
// visible text, tooltips and popups inside the viewport; measures the first-view transfer; saves deck screenshots
// next to this file at deviceScaleFactor 2 (1280 and 375 runs), quantised so each stays under 1 MB.
// Usage: (cd apps/field-to-faucet/web && python3 -m http.server 8731 &) ; node apps/field-to-faucet/web/qa/run_qa.cjs [baseUrl] [--shots-dir=DIR]
const { chromium } = require("playwright");
const path = require("path");
const { execFileSync } = require("child_process");

const BASE = process.argv.find((a) => /^https?:/.test(a)) || "http://localhost:8731/";
const OUT = __dirname;
const EXTRA = (process.argv.find((a) => a.startsWith("--shots-dir=")) || "").split("=")[1] || null; // optional extra section shots
const problems = [];
const info = [];
const shots = [];

async function run(width, height, tag, dsf) {
  // Plain chromium.launch() in this headless container emits "GL Driver Message ... GPU stall due to ReadPixels"
  // warnings from its default GL backend while compositing the WebGL map (not from page code). The SwiftShader
  // ANGLE backend avoids them, so the console check below stays strict.
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: dsf });
  const msgs = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) msgs.push(`[${tag}] console.${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => msgs.push(`[${tag}] pageerror: ${e.message}`));
  page.on("requestfailed", (r) => msgs.push(`[${tag}] requestfailed: ${r.url()} ${r.failure()?.errorText}`));
  const transfer = new Map();
  page.on("response", async (r) => {
    if (r.status() >= 400) msgs.push(`[${tag}] HTTP ${r.status()}: ${r.url()}`);
    try { const b = await r.body(); transfer.set(r.url(), b.length); } catch (_) { /* redirects etc. */ }
  });
  const deck = dsf > 1; // deck screenshots only from the high-DPI runs
  const save = (name) => { shots.push(path.join(OUT, name)); return path.join(OUT, name); };
  const shotEl = async (sel, name, { maxH } = {}) => {
    if (!deck) return;
    const loc = page.locator(sel).first();
    await staticBar(true);
    await loc.scrollIntoViewIfNeeded();
    await page.waitForTimeout(250);
    const bb = await loc.boundingBox();
    if (!bb) { problems.push(`[${tag}] screenshot target missing: ${sel}`); return; }
    const sy = await page.evaluate(() => window.scrollY);
    const clip = { x: Math.max(0, bb.x - 8), y: bb.y + sy - 8, width: Math.min(width, bb.width + 16), height: Math.min(maxH || 1e9, bb.height + 16) };
    await page.screenshot({ path: save(name), fullPage: true, clip });
    await staticBar(false);
  };
  // element/clip screenshots: the sticky top bar would otherwise be painted over the clipped area
  const staticBar = (on) => page.evaluate((v) => { let st = document.getElementById("qa-static"); if (v && !st) { st = document.createElement("style"); st.id = "qa-static"; st.textContent = ".topbar{position:static!important}"; document.head.appendChild(st); } if (!v && st) st.remove(); }, on);
  const extra = (loc, name) => (EXTRA ? page.locator(loc).screenshot({ path: path.join(EXTRA, name) }) : null);

  const noHScroll = async (where) => {
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    if (sw[0] > sw[1]) problems.push(`[${tag}] horizontal scroll on ${where}: scrollWidth ${sw[0]} > ${sw[1]}`);
  };
  const noMock = async (where) => {
    const st = await page.evaluate(() => ({ banner: !document.getElementById("mock-banner").hidden, lib: !document.getElementById("lib-banner").hidden, text: document.getElementById("mock-banner").textContent, chips: [...document.querySelectorAll(".mock-chip")].filter((e) => e.offsetParent !== null).length }));
    if (st.banner) problems.push(`[${tag}] MOCK/missing-data banner visible on ${where}: ${st.text}`);
    if (st.lib) problems.push(`[${tag}] library banner visible on ${where}`);
    if (st.chips) problems.push(`[${tag}] ${st.chips} MOCK chips visible on ${where}`);
  };
  const noBadText = async (where) => {
    const bad = await page.evaluate(() => {
      const t = document.body.innerText;
      const m = t.match(/.{0,40}\b(NaN|undefined|null|Infinity|\[object Object\])\b.{0,40}/g);
      return m ? m.slice(0, 5) : [];
    });
    if (bad.length) problems.push(`[${tag}] bad tokens in visible text on ${where}: ${bad.join(" | ")}`);
  };
  const inViewport = async (sel, what) => {
    const r = await page.evaluate((s) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return { l: b.left, r: b.right, w: document.documentElement.clientWidth, vis: b.width > 0 }; }, sel);
    if (!r) { problems.push(`[${tag}] ${what}: element not found (${sel})`); return; }
    if (r.vis && (r.l < 0 || r.r > r.w + 0.5)) problems.push(`[${tag}] ${what} overflows the viewport: left ${Math.round(r.l)}, right ${Math.round(r.r)} > ${r.w}`);
  };

  // ---------------- City
  await page.goto(BASE + "#city", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const firstKB = [...transfer.values()].reduce((a, b) => a + b, 0) / 1024;
  const dataFiles = [...transfer.keys()].filter((u) => /\/data\//.test(u)).map((u) => u.split("/data/")[1]);
  info.push(`[${tag}] first view (#city, networkidle): ${transfer.size} requests, ${Math.round(firstKB)} KB; data files: ${dataFiles.join(", ")}`);
  if (dataFiles.some((f) => /fields\.geojson|field_detail|strategies/.test(f))) problems.push(`[${tag}] farmer data loaded on the city view`);
  await noMock("city");
  await noBadText("city");
  const hero = (await page.textContent("#city-h")).trim();
  const impactText = () => page.$eval("#impact-text", (el) => { const c = el.cloneNode(true); c.querySelectorAll(".tip-body").forEach((t) => t.remove()); return c.textContent.trim(); });
  const impact = await impactText();
  const kpis = await page.textContent("#city-kpis");
  if (!hero || /Loading/.test(hero)) problems.push(`[${tag}] hero not rendered: ${hero}`);
  if (!/Nitrate from upstream — mostly farmland — forced Des Moines to run its nitrate-removal plant/.test(hero) || !/NASA satellites show which fields sit bare on wet soil/.test(hero)) problems.push(`[${tag}] hero wording: ${hero}`);
  if (!/up to 56 days \(homes: 40\)/.test(hero)) problems.push(`[${tag}] 2025 hero ban should read "up to 56 days (homes: 40)": ${hero}`);
  const heroSrc = await page.textContent("#city-h-src");
  if (!/92% of the nitrogen entering Iowa streams/.test(heroSrc) || !/inrs_nonpoint_share_pct/.test(heroSrc)) problems.push(`[${tag}] hero source note (INRS 92% nonpoint + fact id) missing: ${heroSrc}`);
  const cityTxt = await page.textContent("#view-city");
  if (/\bat the intake\b|River intake was|kept on upstream fields|stays on the fields|already paid for|up to ~\$|tap met the standard/.test(cityTxt)) problems.push(`[${tag}] old wording (intake / kept on fields / already paid) still on the city view`);
  if (!/Van Meter \(upstream of the intake\)/.test(cityTxt)) problems.push(`[${tag}] gauge should be named "Raccoon River at Van Meter (upstream of the intake)"`);
  if (!/incl\. capital/.test(kpis)) problems.push(`[${tag}] 2025 KPI cost should say "incl. capital": ${kpis}`);
  if (!/homes: 40/.test(kpis)) problems.push(`[${tag}] ban KPI should give the homes figure`);
  if (!/nitrogen/.test(impact) || !/fewer plant day/.test(impact) || !/shorter/.test(impact) || !/operating cost avoided/.test(impact) || !/indicative/.test(impact)) problems.push(`[${tag}] impact sentence incomplete: ${impact}`);
  if (!/Seen from space/.test(await page.textContent("#view-city .hero"))) problems.push(`[${tag}] NASA one-liner above the slider missing`);
  const tileOrder = await page.$$eval("#impact-tiles .itile-l", (els) => els.map((e) => e.textContent));
  if (!/nitrogen/.test(tileOrder[0] || "")) problems.push(`[${tag}] first impact tile should be nitrogen kept: ${tileOrder[0]}`);
  if (tag === "1280") info.push(`HERO 2025: ${hero}`, `IMPACT 2025 @25%: ${impact.replace(/\s+/g, " ")}`);
  const banLink = await page.$$eval("#city-kpis .kpi:nth-child(4) a", (as) => as.map((a) => a.textContent));
  if (!banLink.length) problems.push(`[${tag}] ban KPI tile has no source link`);
  else if (/Field to Faucet/.test(banLink.join(" "))) problems.push(`[${tag}] ban KPI link should name CIWW: ${banLink}`);
  const valuetext = await page.$eval("#adopt-hero", (el) => el.getAttribute("aria-valuetext"));
  if (!valuetext || !/corn and soy/.test(valuetext)) problems.push(`[${tag}] hero slider aria-valuetext missing: ${valuetext}`);
  if (await page.$eval("#adopt-hero", (el) => !!el.closest("[aria-live]"))) problems.push(`[${tag}] slider is inside an aria-live region`);
  // ban tooltip stays in the viewport (hover; on phones it is a fixed bottom sheet)
  await page.hover("#impact-tiles .itile:nth-child(3) .tip");
  await page.waitForTimeout(100);
  await inViewport("#impact-tiles .itile:nth-child(3) .tip-body", "ban tooltip");
  await page.mouse.move(2, 2);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  if (tag === "1280") await page.screenshot({ path: save("city-hero-1280.png") });
  if (tag === "1280") await page.screenshot({ path: save("city-full-1280.png"), fullPage: true });
  if (tag === "375") {
    const end = await page.evaluate(() => { const k = document.getElementById("city-lede"); return k.getBoundingClientRect().bottom + window.scrollY + 12; });
    await staticBar(true);
    await page.screenshot({ path: save("city-375.png"), fullPage: true, clip: { x: 0, y: 0, width, height: end } });
    await staticBar(false);
  }

  // sliders: hero slider drives the replay slider and the deltas
  await page.$eval("#adopt-hero", (el) => { el.value = 50; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d50 = await page.textContent("#impact-tiles");
  const replayVal = await page.$eval("#adopt", (el) => el.value);
  if (replayVal !== "50") problems.push(`[${tag}] replay slider not synced with hero slider (${replayVal})`);
  await page.$eval("#adopt", (el) => { el.value = 0; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const leg0 = await page.textContent("#replay-legend");
  if (/With cover on 0%|With 0%/.test(leg0)) problems.push(`[${tag}] replay legend shows a 0% series`);
  await noBadText("city @0%");
  await page.$eval("#adopt", (el) => { el.value = 5; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const t5 = await impactText();
  if (/\b1 fewer plant days\b|~1 days|~1 weeks/.test(t5)) problems.push(`[${tag}] pluralisation: ${t5}`);
  await page.$eval("#adopt", (el) => { el.value = 25; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d25 = await page.textContent("#impact-tiles");
  if (d50 === d25) problems.push(`[${tag}] impact tiles did not change with slider`);
  // band toggle
  await page.check("#replay-band");
  await page.waitForTimeout(150);
  if (tag === "1280") await shotEl("#sec-replay", "city-replay-1280.png");
  await extra("#sec-replay", `city-replay-${tag}.png`);
  await page.uncheck("#replay-band");

  // replay year 2025 -> 2026 -> 2025
  const yearBtns = await page.$$("#year-switch button");
  if (yearBtns.length >= 2) {
    await page.click("#year-switch button:nth-child(2)");
    await page.waitForTimeout(300);
    const hero26 = (await page.textContent("#city-h")).trim();
    const impact26 = await impactText();
    const kpi26 = await page.textContent("#city-kpis");
    if (hero26 === hero) problems.push(`[${tag}] hero did not change with the replay year`);
    if (/2026/.test(hero26) && !/estimate/.test(kpi26)) problems.push(`[${tag}] 2026 days × $/day cost must say "estimate": ${kpi26}`);
    if (!/23 days for homes, 42 for businesses/.test(hero26) || !/a record 193 days \(Jan–Jul\)/.test(hero26)) problems.push(`[${tag}] 2026 hero wording: ${hero26}`);
    if (!/\$1\.6–3\.1M/.test(kpi26) || !/longest run on record \(previous most: 177 days in 2015/.test(kpi26)) problems.push(`[${tag}] 2026 KPI cost/record wording: ${kpi26}`);
    if (tag === "1280") info.push(`HERO 2026: ${hero26}`, `IMPACT 2026 @25%: ${impact26.replace(/\s+/g, " ")}`);
    await noBadText("city 2026");
    if (EXTRA && tag === "1280") await page.screenshot({ path: path.join(EXTRA, `city-hero-2026-${tag}.png`) });
    await page.click("#year-switch button:nth-child(1)");
    await page.waitForTimeout(200);
  } else problems.push(`[${tag}] replay year switch missing`);

  // river toggles (river group loads after the hero)
  await page.waitForSelector("#river-site button", { timeout: 8000 }).catch(() => problems.push(`[${tag}] river chart controls did not render`));
  await page.click("#river-site button:nth-child(2)");
  await page.click("#river-range button:nth-child(1)");
  await page.waitForTimeout(200);
  await extra("#sec-river", `city-river-${tag}.png`);
  await page.click("#river-site button:nth-child(1)");
  await page.click("#river-range button:nth-child(2)");
  // hotspot map: click the first hotspot in the list -> popup
  await page.waitForSelector("#hotspot-list button", { timeout: 8000 }).catch(() => problems.push(`[${tag}] hotspot list did not render`));
  await page.click("#hotspot-list button");
  await page.waitForTimeout(1400);
  if (!(await page.$(".maplibregl-popup"))) problems.push(`[${tag}] hotspot popup did not open`);
  else await inViewport(".maplibregl-popup-content", "hotspot popup");
  const hsNote = await page.textContent("#hotspot-note");
  if (!/modelled leak index \(not measured\)/.test(hsNote)) problems.push(`[${tag}] hotspot note wording: ${hsNote}`);
  if (tag === "1280") await shotEl("#sec-map", "city-hotspots-1280.png");
  await extra("#sec-map", `city-map-${tag}.png`);
  await extra("#sec-outlook", `city-outlook-${tag}.png`);
  const skill = await page.textContent("#outlook-skill");
  if (!/typical error/.test(skill)) problems.push(`[${tag}] outlook skill wording: ${skill}`);
  const roles = await page.$$eval("canvas:not(.maplibregl-canvas)", (cs) => cs.filter((c) => c.getAttribute("role") !== "img").map((c) => c.id || "(no id)"));
  if (roles.length) problems.push(`[${tag}] canvases without role="img": ${roles.join(", ")}`);
  await noBadText("city (all loaded)");
  await noHScroll("city");

  // ---------------- Farmer (tab click, not a reload)
  await page.click('.tabs a[data-view="farmer"]');
  await page.waitForTimeout(2000);
  await noMock("farmer map");
  await page.click("#pick-sample");
  await page.waitForSelector("#field-content:not([hidden])", { timeout: 8000 }).catch(() => problems.push(`[${tag}] field panel did not open`));
  await page.waitForTimeout(900);
  const typicalHead = await page.textContent("#field-head h2");
  if (!/^Field near .+\(F\d+\)/.test(typicalHead.trim())) problems.push(`[${tag}] field name should read "Field near <town> (F…)": ${typicalHead}`);
  const typHead = await page.textContent("#field-head");
  if (tag === "1280") info.push(`TYPICAL FIELD: ${typHead.replace(/\s+/g, " ").slice(0, 260)}`);
  if (!/modelled leak \(estimate, not measured\)/.test(typHead)) problems.push(`[${tag}] leak label must say "modelled leak (estimate, not measured)"`);
  if (/lose almost nothing/.test(typHead)) problems.push(`[${tag}] old "dry years lose almost nothing" wording`);
  if (await page.isHidden("#pick-leaky")) problems.push(`[${tag}] "show a leaky field" button not offered after the typical field`);
  const live = await page.textContent("#field-live");
  if (!/Selected Field near/.test(live)) problems.push(`[${tag}] aria-live announcement missing: ${live}`);
  const cards = await page.$$eval(".card", (els) => els.length);
  if (cards < 3) problems.push(`[${tag}] expected >= 3 strategy cards, got ${cards}`);
  const cmpRows = await page.$$eval("#strategy-compare tbody tr", (els) => els.length);
  if (cmpRows !== cards) problems.push(`[${tag}] comparison table rows (${cmpRows}) != cards (${cards})`);
  const panel = await page.textContent("#field-panel");
  if (!/in 8 of 10 years/i.test(panel)) problems.push(`[${tag}] field panel lacks the "in 8 of 10 years" range`);
  if (!/wet year like 2016/i.test(panel)) problems.push(`[${tag}] field panel lacks the 2016 wet-year example`);
  if (!/not verified/i.test(panel)) problems.push(`[${tag}] unknown cost should read "not verified"`);
  if (!/Leak, lb N\/acre/.test(panel)) problems.push(`[${tag}] leak calendar lacks the lb N/acre row`);
  if (!/cost-share of \$\d+–\$\d+\/acre/.test(panel)) problems.push(`[${tag}] rye money line (cost vs cost-share) missing`);
  if (!/cost-share of \$20–\$74\/acre \(state \$20–\$30; EQIP ~\$74, third-party figure\)/.test(panel)) problems.push(`[${tag}] cost-share wording should be "$20–$74/acre (state $20–$30; EQIP ~$74, third-party figure)"`);
  if (!/28% \(SD 26\)[^.]*averaged across the corn-soy rotation, and by 30% \(SD 27\) in the soybean year/.test(panel)) problems.push(`[${tag}] rye trial wording (28% rotation avg, 30% SD 27 soybean year) missing`);
  if (await page.$("#prio-formula")) problems.push(`[${tag}] score formula box should be gone from the sidebar`);
  const openDetails = await page.$$eval(".card details[open]", (els) => els.length);
  if (openDetails) problems.push(`[${tag}] card details should start closed (${openDetails} open)`);
  if (!/not a replacement for your agronomist/i.test(await page.textContent("#view-farmer"))) problems.push(`[${tag}] agronomist note missing`);
  const firstBefore = await page.textContent(".card h3");
  await page.$eval("#w-n", (el) => { el.value = 0; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.$eval("#w-cost", (el) => { el.value = 3; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const firstAfter = await page.textContent(".card h3");
  if (firstBefore === firstAfter) problems.push(`[${tag}] priorities did not re-rank cards (${firstBefore})`);
  // all weights 0 -> prompt and "not scored", never "0/100"
  for (const k of ["n", "yield", "soil", "cost"]) await page.$eval(`#w-${k}`, (el) => { el.value = 0; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const allZero = await page.textContent("#field-panel");
  if (!/move a slider/i.test(allZero) || /0\/100/.test(allZero)) problems.push(`[${tag}] all-zero weights should prompt and show "not scored"`);
  const vt = await page.$eval("#w-n", (el) => el.getAttribute("aria-valuetext"));
  if (vt !== "not at all") problems.push(`[${tag}] priority slider aria-valuetext: ${vt}`);
  for (const [k, v] of [["n", 2], ["yield", 2], ["soil", 1], ["cost", 1]]) await page.$eval(`#w-${k}`, (el, val) => { el.value = val; el.dispatchEvent(new Event("input", { bubbles: true })); }, v);
  await noMock("farmer field");
  await noBadText("farmer (typical)");
  if (tag === "1280") {
    await shotEl("#field-panel .field-grid", "farmer-panel-1280.png");
    // comparison table + cards: from the heading to the cards' end
    await staticBar(true);
    await page.locator("#strategy-compare").scrollIntoViewIfNeeded();
    const r = await page.evaluate(() => {
      const a = document.querySelector("#field-panel .cards-head").getBoundingClientRect();
      const b = document.getElementById("strategy-cards").getBoundingClientRect();
      return { y: a.top + window.scrollY - 8, h: b.bottom - a.top + 16 };
    });
    await page.screenshot({ path: path.join(OUT, "farmer-cards-1280.png"), fullPage: true, clip: { x: 0, y: r.y, width, height: Math.min(r.h, 2200) } });
    await staticBar(false);
  }
  if (tag === "375") {
    const r = await page.evaluate(() => { const a = document.getElementById("field-panel").getBoundingClientRect(); const cal = document.getElementById("cal-note").getBoundingClientRect(); return { y: a.top + window.scrollY, h: cal.bottom - a.top + 16 }; });
    await staticBar(true);
    await page.screenshot({ path: save("farmer-375.png"), fullPage: true, clip: { x: 0, y: r.y, width, height: r.h } });
    await staticBar(false);
  }
  // leaky field second
  await page.click("#pick-leaky");
  await page.waitForTimeout(1200);
  const leakyHead = await page.textContent("#field-head h2");
  if (leakyHead === typicalHead) problems.push(`[${tag}] "show a leaky field" did not change the field`);
  await noBadText("farmer (leaky)");
  // keyboard search by town and by id
  await page.fill("#field-q", "F00002");
  await page.press("#field-q", "Enter");
  await page.waitForTimeout(900);
  if (!/F00002/.test(await page.textContent("#field-head h2"))) problems.push(`[${tag}] field search by ID did not select F00002`);
  const town = await page.$eval("#field-list option", (o) => o.value).catch(() => null);
  if (town) {
    await page.fill("#field-q", town);
    await page.press("#field-q", "Enter");
    await page.waitForTimeout(900);
    if (!/Nearest field to|Selected/.test(await page.textContent("#field-live"))) problems.push(`[${tag}] field search by town gave no announcement`);
  } else problems.push(`[${tag}] field search datalist empty`);
  // real map click on the centre of the farm map (fields are dense there)
  await page.locator("#farm-map").scrollIntoViewIfNeeded();
  const box = await page.locator("#farm-map").boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(800);
  await noHScroll("farmer");
  const hash = await page.evaluate(() => location.hash);
  if (!/^#farmer\/F\d+/.test(hash)) problems.push(`[${tag}] hash not updated after selection: ${hash}`);

  // deep link (fresh load) and a bad deep link
  await page.goto(BASE + hash, { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  if (await page.isHidden("#field-content")) problems.push(`[${tag}] deep link ${hash} did not open the field`);
  await page.goto(BASE + "#farmer/F99999", { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  if (!/not found/i.test(await page.textContent("#field-empty"))) problems.push(`[${tag}] bad deep link should say "not found"`);

  // ---------------- Method (tab click)
  await page.click('.tabs a[data-view="method"]');
  await page.waitForTimeout(600);
  const meth = await page.textContent("#view-method");
  if (!/under-predicted 2025-26/.test(meth)) problems.push(`[${tag}] method lacks the honest 2025 line`);
  if (!/one hypothesis/.test(meth)) problems.push(`[${tag}] honest line should say "one hypothesis"`);
  if (!/No weather forecast/i.test(meth)) problems.push(`[${tag}] method lacks "no weather forecast"`);
  const hashLinkTargets = await page.$$eval('a[href^="#"][target]', (as) => as.length);
  if (hashLinkTargets) problems.push(`[${tag}] ${hashLinkTargets} in-page links open a new tab`);
  await noMock("method");
  await noBadText("method");
  if (tag === "1280") {
    const h = await page.evaluate(() => document.getElementById("outlook-val").parentElement.getBoundingClientRect().top + window.scrollY - 30);
    await page.screenshot({ path: save("method-1280.png"), fullPage: true, clip: { x: 0, y: 0, width, height: h } });
  }
  await noHScroll("method");
  // back to city via tab
  await page.click('.tabs a[data-view="city"]');
  await page.waitForTimeout(500);
  await noHScroll("city (again)");

  problems.push(...msgs);
  await browser.close();
}

// Keep each PNG under 1 MB: quantise to 128 colours (then fewer, then downscale) with Pillow.
function shrink(files) {
  const py = `
import sys, os
from PIL import Image
for f in sys.argv[1:]:
    if not os.path.exists(f): continue
    im = Image.open(f).convert("RGB")
    for colors, scale in [(128, 1), (64, 1), (64, 0.8), (48, 0.7), (32, 0.6)]:
        q = im if scale == 1 else im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)
        q.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(f, optimize=True)
        if os.path.getsize(f) < 1000000: break
    print(f"{os.path.basename(f)}: {im.width}x{im.height} -> {os.path.getsize(f)//1024} KB (colors {colors}, scale {scale})")
`;
  try { info.push(execFileSync("python3", ["-c", py, ...files]).toString().trim()); } catch (e) { problems.push(`screenshot shrink failed: ${e.message}`); }
}

(async () => {
  await run(1280, 860, "1280", 2);
  await run(768, 1000, "768", 1);
  await run(375, 760, "375", 2);
  shrink([...new Set(shots.concat([path.join(OUT, "farmer-cards-1280.png")]))]);
  console.log(info.join("\n"));
  if (problems.length) { console.log("QA PROBLEMS:\n" + problems.join("\n")); process.exitCode = 1; }
  else console.log("QA OK: no console errors/warnings, no MOCK banner/chips, no NaN/undefined/null text, no horizontal scroll at 1280/768/375 px, interactions work.");
})();
