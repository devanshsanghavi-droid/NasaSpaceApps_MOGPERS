// Playwright QA: loads each view at 1280 px and 375 px, switches the replay year, moves the sliders, clicks a field,
// switches tabs; asserts no console errors/warnings, no failed requests, no MOCK banner or chips (all data real),
// no horizontal scroll; measures the first-view transfer; saves screenshots next to this file (deviceScaleFactor 1).
// Usage: (cd apps/field-to-faucet/web && python3 -m http.server 8731 &) ; node apps/field-to-faucet/web/qa/run_qa.cjs [baseUrl] [--shots-dir=DIR]
const { chromium } = require("playwright");
const path = require("path");

const BASE = process.argv.find((a) => /^https?:/.test(a)) || "http://localhost:8731/";
const OUT = __dirname;
const EXTRA = (process.argv.find((a) => a.startsWith("--shots-dir=")) || "").split("=")[1] || null; // optional section shots
const problems = [];
const info = [];

async function run(width, height, tag) {
  // Plain chromium.launch() in this headless container emits "GL Driver Message ... GPU stall due to ReadPixels"
  // warnings from its default GL backend while compositing the WebGL map (not from page code). The SwiftShader
  // ANGLE backend avoids them, so the console check below stays strict.
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader"] });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  const msgs = [];
  page.on("console", (m) => { if (["error", "warning"].includes(m.type())) msgs.push(`[${tag}] console.${m.type()}: ${m.text()}`); });
  page.on("pageerror", (e) => msgs.push(`[${tag}] pageerror: ${e.message}`));
  page.on("requestfailed", (r) => msgs.push(`[${tag}] requestfailed: ${r.url()} ${r.failure()?.errorText}`));
  const transfer = new Map();
  page.on("response", async (r) => {
    if (r.status() >= 400) msgs.push(`[${tag}] HTTP ${r.status()}: ${r.url()}`);
    try { const b = await r.body(); transfer.set(r.url(), b.length); } catch (_) { /* redirects etc. */ }
  });
  const shot = (name, opts = {}) => page.screenshot({ path: path.join(OUT, name), ...opts });
  const extra = (loc, name) => (EXTRA ? page.locator(loc).screenshot({ path: path.join(EXTRA, name) }) : null);

  const noHScroll = async (where) => {
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    if (sw[0] > sw[1]) problems.push(`[${tag}] horizontal scroll on ${where}: scrollWidth ${sw[0]} > ${sw[1]}`);
  };
  const noMock = async (where) => {
    const st = await page.evaluate(() => ({ banner: !document.getElementById("mock-banner").hidden, text: document.getElementById("mock-banner").textContent, chips: [...document.querySelectorAll(".mock-chip")].filter((e) => e.offsetParent !== null).length }));
    if (st.banner) problems.push(`[${tag}] MOCK banner visible on ${where}: ${st.text}`);
    if (st.chips) problems.push(`[${tag}] ${st.chips} MOCK chips visible on ${where}`);
  };

  // ---------------- City
  await page.goto(BASE + "#city", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const firstKB = [...transfer.values()].reduce((a, b) => a + b, 0) / 1024;
  const dataFiles = [...transfer.keys()].filter((u) => /\/data\//.test(u)).map((u) => u.split("/data/")[1]);
  info.push(`[${tag}] first view (#city, networkidle): ${transfer.size} requests, ${Math.round(firstKB)} KB; data files: ${dataFiles.join(", ")}`);
  if (dataFiles.some((f) => /fields\.geojson|field_detail|strategies/.test(f))) problems.push(`[${tag}] farmer data loaded on the city view`);
  await noMock("city");
  const hero = (await page.textContent("#city-h")).trim();
  const impactText = () => page.$eval("#impact-text", (el) => { const c = el.cloneNode(true); c.querySelectorAll(".tip-body").forEach((t) => t.remove()); return c.textContent.trim(); });
  const impact = await impactText();
  if (!hero || /Loading/.test(hero)) problems.push(`[${tag}] hero not rendered: ${hero}`);
  if (!/incl\. capital/.test(hero)) problems.push(`[${tag}] 2025 hero should label the cost "incl. capital": ${hero}`);
  if (!/fewer plant days/.test(impact) || !/operating cost avoided/.test(impact) || !/indicative \(proxy rule\)/.test(impact)) problems.push(`[${tag}] impact sentence incomplete: ${impact}`);
  if (tag === "1280") info.push(`HERO 2025: ${hero}`, `IMPACT 2025 @25%: ${impact.replace(/\s+/g, " ")}`);
  const banLink = await page.$$eval("#city-kpis .kpi:nth-child(4) a", (as) => as.map((a) => a.href));
  if (!banLink.length) problems.push(`[${tag}] ban KPI tile has no source link`);
  if (tag === "1280") await shot("city-hero-1280.png");
  if (tag === "1280") await shot("city-full-1280.png", { fullPage: true });
  if (tag === "375") await shot("city-375.png", { fullPage: true });

  // sliders: hero slider drives the replay slider and the deltas
  await page.$eval("#adopt-hero", (el) => { el.value = 50; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d50 = await page.textContent("#impact-tiles");
  const replayVal = await page.$eval("#adopt", (el) => el.value);
  if (replayVal !== "50") problems.push(`[${tag}] replay slider not synced with hero slider (${replayVal})`);
  await page.$eval("#adopt", (el) => { el.value = 25; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d25 = await page.textContent("#impact-tiles");
  if (d50 === d25) problems.push(`[${tag}] impact tiles did not change with slider`);
  // band toggle
  await page.check("#replay-band");
  await page.waitForTimeout(100);
  if (EXTRA) await extra("#sec-replay", `city-replay-${tag}.png`);
  await page.uncheck("#replay-band");

  // replay year 2025 -> 2026 -> 2025
  const yearBtns = await page.$$("#year-switch button");
  if (yearBtns.length >= 2) {
    await page.click("#year-switch button:nth-child(2)");
    await page.waitForTimeout(300);
    const hero26 = (await page.textContent("#city-h")).trim();
    const impact26 = await impactText();
    if (hero26 === hero) problems.push(`[${tag}] hero did not change with the replay year`);
    if (/2026/.test(hero26) && !/estimate/.test(hero26)) problems.push(`[${tag}] 2026 days × $/day cost must say "estimate": ${hero26}`);
    if (tag === "1280") info.push(`HERO 2026: ${hero26}`, `IMPACT 2026 @25%: ${impact26.replace(/\s+/g, " ")}`);
    if (EXTRA && tag === "1280") await page.screenshot({ path: path.join(EXTRA, `city-hero-2026-${tag}.png`) });
    await page.click("#year-switch button:nth-child(1)");
    await page.waitForTimeout(200);
  } else problems.push(`[${tag}] replay year switch missing`);

  // river toggles
  await page.click("#river-site button:nth-child(2)");
  await page.click("#river-range button:nth-child(1)");
  await page.waitForTimeout(200);
  if (EXTRA) await extra("#sec-river", `city-river-${tag}.png`);
  await page.click("#river-site button:nth-child(1)");
  await page.click("#river-range button:nth-child(2)");
  // hotspot map: click the first hotspot in the list -> popup
  await page.waitForSelector("#hotspot-list button", { timeout: 8000 }).catch(() => problems.push(`[${tag}] hotspot list did not render`));
  await page.click("#hotspot-list button");
  await page.waitForTimeout(1200);
  if (!(await page.$(".maplibregl-popup"))) problems.push(`[${tag}] hotspot popup did not open`);
  if (EXTRA) await extra("#sec-map", `city-map-${tag}.png`);
  if (EXTRA) await extra("#sec-outlook", `city-outlook-${tag}.png`);
  await noHScroll("city");

  // ---------------- Farmer (tab click, not a reload)
  await page.click('.tabs a[data-view="farmer"]');
  await page.waitForTimeout(2000);
  await noMock("farmer map");
  await page.click("#pick-sample");
  await page.waitForSelector("#field-content:not([hidden])", { timeout: 8000 }).catch(() => problems.push(`[${tag}] field panel did not open`));
  await page.waitForTimeout(900);
  const cards = await page.$$eval(".card", (els) => els.length);
  if (cards < 3) problems.push(`[${tag}] expected >= 3 strategy cards, got ${cards}`);
  const panel = await page.textContent("#field-panel");
  if (!/in 8 of 10 years/i.test(panel)) problems.push(`[${tag}] field panel lacks the "in 8 of 10 years" range`);
  if (!/wet year like 2016/i.test(panel)) problems.push(`[${tag}] field panel lacks the 2016 wet-year example`);
  if (!/cost not verified/i.test(panel)) problems.push(`[${tag}] unknown cost should read "cost not verified"`);
  if (!/Leak, lb N\/acre/.test(panel)) problems.push(`[${tag}] leak calendar lacks the lb N/acre row`);
  if (!/not a replacement for your agronomist/i.test(await page.textContent("#view-farmer"))) problems.push(`[${tag}] agronomist note missing`);
  const firstBefore = await page.textContent(".card h3");
  await page.$eval("#w-n", (el) => { el.value = 0; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.$eval("#w-cost", (el) => { el.value = 3; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const firstAfter = await page.textContent(".card h3");
  if (firstBefore === firstAfter) problems.push(`[${tag}] priorities did not re-rank cards (${firstBefore})`);
  await page.$eval("#w-n", (el) => { el.value = 2; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.$eval("#w-cost", (el) => { el.value = 1; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await noMock("farmer field");
  if (tag === "1280") await page.locator("#field-panel").screenshot({ path: path.join(OUT, "farmer-panel-1280.png") });
  if (tag === "375") await shot("farmer-375.png", { fullPage: true });
  // real map click on the centre of the farm map (fields are dense there)
  await page.locator("#farm-map").scrollIntoViewIfNeeded();
  const box = await page.locator("#farm-map").boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(800);
  await noHScroll("farmer");
  const hash = await page.evaluate(() => location.hash);
  if (!/^#farmer\/F\d+/.test(hash)) problems.push(`[${tag}] hash not updated after selection: ${hash}`);

  // deep link (fresh load)
  await page.goto(BASE + hash, { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  if (await page.isHidden("#field-content")) problems.push(`[${tag}] deep link ${hash} did not open the field`);

  // ---------------- Method (tab click)
  await page.click('.tabs a[data-view="method"]');
  await page.waitForTimeout(400);
  const meth = await page.textContent("#view-method");
  if (!/under-predicted 2025-26/.test(meth)) problems.push(`[${tag}] method lacks the honest 2025 line`);
  if (!/No weather forecast/i.test(meth)) problems.push(`[${tag}] method lacks "no weather forecast"`);
  await noMock("method");
  if (tag === "1280") await shot("method-1280.png", { fullPage: true });
  await noHScroll("method");
  // back to city via tab
  await page.click('.tabs a[data-view="city"]');
  await page.waitForTimeout(500);
  await noHScroll("city (again)");

  problems.push(...msgs);
  await browser.close();
}

(async () => {
  await run(1280, 860, "1280");
  await run(375, 760, "375");
  console.log(info.join("\n"));
  if (problems.length) { console.log("QA PROBLEMS:\n" + problems.join("\n")); process.exitCode = 1; }
  else console.log("QA OK: no console errors/warnings, no MOCK banner/chips, no horizontal scroll at 375 px, interactions work.");
})();
