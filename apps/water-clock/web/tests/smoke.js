// Smoke test for the Water Clock web app (Playwright, Chromium).
// Usage: BASE=http://127.0.0.1:8765/ LIB_DIR=/path/with/npm-packs node smoke.js [shotsDir]
// LIB_DIR (optional) must contain maplibre-gl-4.7.1/package/dist and chart.js-4.4.4/package/dist
// (from `npm pack`), used to serve the pinned CDN files when the CDN hosts are unreachable.
// Basemap tiles are blocked on purpose so the plain-style fallback is exercised.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE = process.env.BASE || 'http://127.0.0.1:8765/';
const LIB = process.env.LIB_DIR || '';
const SHOTS = process.argv[2] || path.join(__dirname, '..', 'screenshots');

function libFile(url) {
  if (!LIB) return null;
  const m = url.match(/maplibre-gl@4\.7\.1\/dist\/(maplibre-gl\.(js|css))/);
  if (m) return path.join(LIB, 'maplibre-gl-4.7.1/package/dist', m[1]);
  const c = url.match(/chart\.js@4\.4\.4\/dist\/(chart\.umd\.js)/);
  if (c) return path.join(LIB, 'chart.js-4.4.4/package/dist', c[1]);
  return null;
}

async function run(width, height, label) {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  const errors = [], expected404 = [], warnings = [];
  page.on('console', m => {
    if (m.type() === 'error') {
      const t = m.text();
      if (/Failed to load resource/.test(t)) expected404.push(t); else errors.push(t);
    } else if (m.type() === 'warning') warnings.push(m.text());
  });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('requestfailed', r => { const u = r.url(); if (u.startsWith(BASE)) errors.push('requestfailed: ' + u); });
  await page.route('**/*', route => {
    const u = route.request().url();
    if (u.startsWith(BASE)) return route.continue();
    const f = libFile(u);
    if (f && fs.existsSync(f)) return route.fulfill({ path: f, contentType: f.endsWith('.css') ? 'text/css' : 'application/javascript' });
    return route.abort();
  });
  const out = { label, width };
  await page.goto(BASE, { waitUntil: 'load' });
  await page.waitForSelector('body.ready', { timeout: 20000 });
  await page.waitForTimeout(800);
  out.mockBanner = await page.isVisible('#mock-banner');
  out.headline = (await page.textContent('#hl-years')).trim() + ' | ' + (await page.textContent('#hl-range')).trim();
  out.hScroll = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await page.screenshot({ path: path.join(SHOTS, `${label}-home.png`) });

  // Use the county search first, then pick a field from the picker (keyboard path), then a map click.
  await page.fill('#county-search', 'Finney');
  await page.press('#county-search', 'Enter');
  await page.waitForSelector('#field-pick', { timeout: 5000 });
  out.countyClock = (await page.textContent('.ck-big')).trim();
  const firstField = await page.$eval('#field-pick option:nth-child(2)', o => o.value);
  await page.selectOption('#field-pick', firstField);
  await page.waitForSelector('.strat', { timeout: 5000 });
  out.fieldClock = (await page.textContent('.ck-big')).trim();
  out.strategyCards = await page.$$eval('.strat', a => a.length);
  out.gains = await page.$$eval('.strat .m-gain', a => a.map(e => e.textContent.trim().replace(/\s+/g, ' ')));
  await page.waitForTimeout(800);
  await page.click('[data-thr="50"]');
  await page.waitForTimeout(200);
  out.fieldClock50 = (await page.textContent('.ck-big')).trim();
  await page.click('[data-thr="30"]');
  // priority slider to "make water last"
  await page.focus('#prio');
  for (let i = 0; i < 10; i++) await page.keyboard.press('ArrowRight');
  out.bestAfterWater = (await page.textContent('.strat.best h4')).trim();
  await page.screenshot({ path: path.join(SHOTS, `${label}-field.png`), fullPage: width < 600 ? false : false });
  // Community view + slider
  await page.click('#tab-community');
  await page.waitForSelector('#sh-pct');
  const before = (await page.textContent('#sh-out')).trim().replace(/\s+/g, ' ');
  await page.$eval('#sh-pct', e => { e.value = 80; e.dispatchEvent(new Event('input', { bubbles: true })); });
  out.sliderText = (await page.textContent('.sh-sentence')).trim().replace(/\s+/g, ' ');
  out.sliderChanged = before !== (await page.textContent('#sh-out')).trim().replace(/\s+/g, ' ');
  await page.click('[data-sort="years"]');
  out.hScrollCommunity = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await page.screenshot({ path: path.join(SHOTS, `${label}-community.png`) });
  // GRACE
  await page.click('#tab-grace');
  await page.waitForTimeout(500);
  out.graceChart = await page.$$eval('#grace-chart', a => a.length === 1);
  out.graceMap = await page.$$eval('#grace-map', a => a.length === 1);
  out.hScrollGrace = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  await page.screenshot({ path: path.join(SHOTS, `${label}-grace.png`) });
  // Data
  await page.click('#tab-data');
  await page.waitForTimeout(300);
  out.validationTables = await page.$$eval('#data-panel table', a => a.length);
  out.sources = await page.$$eval('.sources li', a => a.length);
  out.hScrollData = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
  // Map click on a field dot: go back to farmer, project a field to pixels, click it.
  await page.click('#tab-farmer');
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(800);
  const px = await page.evaluate(() => {
    const m = window.__waterClockMap;
    if (!m) return null;
    const r = m.getCanvas().getBoundingClientRect();
    const vis = m.queryRenderedFeatures({ layers: ['fields'] }).map(f => {
      const p = m.project(f.geometry.coordinates);
      return { x: r.left + p.x, y: r.top + p.y, id: f.properties.id };
    }).filter(q => {
      const inside = sel => { const e = document.querySelector(sel); if (!e) return false; const b = e.getBoundingClientRect(); return q.x > b.left - 8 && q.x < b.right + 8 && q.y > b.top - 8 && q.y < b.bottom + 8; };
      return q.y > Math.max(r.top, 0) + 10 && q.y < Math.min(r.bottom, innerHeight) - 10 && q.x > r.left + 10 && q.x < r.right - 50 &&
        !inside('#legend') && !inside('.grid-toggle') && !inside('.maplibregl-ctrl-top-right') && !inside('.maplibregl-ctrl-bottom-right');
    });
    return vis[0] || null;
  });
  out.mapClick = null;
  if (px) {
    await page.mouse.click(px.x, px.y);
    await page.waitForTimeout(500);
    out.mapClick = { id: px.id, panel: (await page.textContent('.ck-sub')).trim() };
  }
  out.errors = errors; out.expected404 = expected404.length; out.warnings = warnings.slice(0, 5);
  await browser.close();
  return out;
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const results = [];
  results.push(await run(1366, 900, 'desktop'));
  results.push(await run(375, 812, 'phone'));
  console.log(JSON.stringify(results, null, 2));
})().catch(e => { console.error(e); process.exit(1); });
