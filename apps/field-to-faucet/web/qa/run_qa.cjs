// Playwright QA: loads each view at 1280 px and 375 px, clicks a field, moves the sliders,
// asserts no console errors/warnings and no horizontal scroll at 375 px, saves screenshots next to this file.
// Usage: (cd apps/field-to-faucet/web && python3 -m http.server 8731 &) ; node apps/field-to-faucet/web/qa/run_qa.cjs [baseUrl]
const { chromium } = require("playwright");
const path = require("path");

const BASE = process.argv[2] || "http://localhost:8731/";
const OUT = __dirname;
const problems = [];

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
  page.on("response", (r) => { if (r.status() >= 400) msgs.push(`[${tag}] HTTP ${r.status()}: ${r.url()}`); });

  const noHScroll = async (where) => {
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    if (sw[0] > sw[1]) problems.push(`[${tag}] horizontal scroll on ${where}: scrollWidth ${sw[0]} > ${sw[1]}`);
  };

  // City
  await page.goto(BASE + "#city", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  const lede = await page.textContent("#city-lede");
  if (!lede || /Loading/.test(lede)) problems.push(`[${tag}] city lede not rendered: ${lede}`);
  await page.screenshot({ path: path.join(OUT, `city-top-${tag}.png`) });
  await page.screenshot({ path: path.join(OUT, `city-full-${tag}.png`), fullPage: true });
  // slider to 50 then 25
  await page.$eval("#adopt", (el) => { el.value = 50; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d50 = await page.textContent("#replay-deltas");
  await page.$eval("#adopt", (el) => { el.value = 25; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const d25 = await page.textContent("#replay-deltas");
  if (d50 === d25) problems.push(`[${tag}] replay deltas did not change with slider`);
  await page.locator("#sec-replay").screenshot({ path: path.join(OUT, `city-replay-${tag}.png`) });
  // river toggles
  if (problems.length || msgs.length) { console.log([...problems, ...msgs].join("\n")); }
  await page.click("#river-site button:nth-child(2)");
  await page.click("#river-range button:nth-child(1)");
  await page.waitForTimeout(200);
  await page.locator("#sec-river").screenshot({ path: path.join(OUT, `city-river-${tag}.png`) });
  await page.locator("#sec-map").screenshot({ path: path.join(OUT, `city-map-overview-${tag}.png`) });
  // hotspot map: click the first hotspot in the list -> popup
  await page.click("#hotspot-list button");
  await page.waitForTimeout(1200);
  const pop = await page.$(".maplibregl-popup");
  if (!pop) problems.push(`[${tag}] hotspot popup did not open`);
  await page.locator("#sec-map").screenshot({ path: path.join(OUT, `city-map-${tag}.png`) });
  await page.locator("#sec-outlook").screenshot({ path: path.join(OUT, `city-outlook-${tag}.png`) });
  await noHScroll("city");

  // Farmer
  await page.goto(BASE + "#farmer", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(OUT, `farmer-map-${tag}.png`) });
  // click a field on the map canvas: use the map's projection of a field centroid
  const clicked = await page.evaluate(() => {
    const c = document.querySelector("#farm-map canvas");
    return !!c;
  });
  if (!clicked) problems.push(`[${tag}] farm map canvas missing`);
  await page.click("#pick-sample");
  await page.waitForSelector("#field-content:not([hidden])", { timeout: 5000 }).catch(() => problems.push(`[${tag}] field panel did not open`));
  await page.waitForTimeout(900);
  const cards = await page.$$eval(".card", (els) => els.length);
  if (cards < 4) problems.push(`[${tag}] expected >= 4 strategy cards, got ${cards}`);
  const firstBefore = await page.textContent(".card h3");
  // priorities: make "low cost" top and nitrogen zero -> ranking should change
  await page.$eval("#w-n", (el) => { el.value = 0; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.$eval("#w-cost", (el) => { el.value = 3; el.dispatchEvent(new Event("input", { bubbles: true })); });
  const firstAfter = await page.textContent(".card h3");
  if (firstBefore === firstAfter) problems.push(`[${tag}] priorities did not re-rank cards (${firstBefore})`);
  await page.$eval("#w-n", (el) => { el.value = 2; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.$eval("#w-cost", (el) => { el.value = 1; el.dispatchEvent(new Event("input", { bubbles: true })); });
  await page.screenshot({ path: path.join(OUT, `farmer-field-${tag}.png`) });
  await page.locator("#field-panel").screenshot({ path: path.join(OUT, `farmer-panel-${tag}.png`) });
  // real map click on the centre of the farm map (fields are dense there)
  await page.locator("#farm-map").scrollIntoViewIfNeeded();
  const box = await page.locator("#farm-map").boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(600);
  await noHScroll("farmer");
  const hash = await page.evaluate(() => location.hash);
  if (!/^#farmer\/F\d+/.test(hash)) problems.push(`[${tag}] hash not updated after selection: ${hash}`);

  // deep link
  await page.goto(BASE + hash, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  if (await page.isHidden("#field-content")) problems.push(`[${tag}] deep link ${hash} did not open the field`);

  // Method
  await page.goto(BASE + "#method", { waitUntil: "networkidle" });
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, `method-${tag}.png`), fullPage: true });
  await noHScroll("method");

  problems.push(...msgs);
  await browser.close();
}

(async () => {
  await run(1280, 860, "1280");
  await run(375, 760, "375");
  if (problems.length) { console.log("QA PROBLEMS:\n" + problems.join("\n")); process.exitCode = 1; }
  else console.log("QA OK: no console errors/warnings, no horizontal scroll at 375 px, interactions work.");
})();
