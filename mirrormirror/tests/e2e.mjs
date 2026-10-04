/* End-to-end: serve the app, feed Chromium a fake front camera, consult the mirror, and read the verdict.
   Usage: node tests/e2e.mjs [--video path.y4m] [--photo path.jpg] [--out dir] [--bundled path/to/www]
   --bundled serves the iOS bundle (ios/MirrorMirror/www after prepare.sh) with the iOS configuration injected and
   every request to a host other than localhost blocked and counted; the test fails if the app tried to leave the device.
   Env:   MM_CHROMIUM    path to an existing Chromium/Chrome binary (default: the one Playwright installed)
          MM_VISION_DIR  path to @mediapipe/tasks-vision 0.10.35 (default: node_modules/@mediapipe/tasks-vision)
          MM_MODEL_PATH  local copy of face_landmarker.task (optional; otherwise fetched from Google) */
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
const { chromium } = createRequire(import.meta.url)('playwright');

const here = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(process.argv.slice(2).map((a, i, arr) => a.startsWith('--') ? [a.slice(2), arr[i + 1]] : []).filter(Boolean));
const BUNDLED = args.bundled ? path.resolve(args.bundled) : null;
const APP = BUNDLED || path.resolve(here, '..');
const VIDEO = args.video || null;
const PHOTO = args.photo || null;
const OUT = args.out || path.join(here, 'out');
const VISION_DIR = process.env.MM_VISION_DIR || path.join(APP, 'node_modules', '@mediapipe', 'tasks-vision');
const MODEL_PATH = process.env.MM_MODEL_PATH || null;
fs.mkdirSync(OUT, { recursive: true });

const MIME = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.webmanifest': 'application/manifest+json', '.png': 'image/png', '.svg': 'image/svg+xml', '.jpg': 'image/jpeg', '.wasm': 'application/wasm', '.task': 'application/octet-stream', '.woff2': 'font/woff2' };
const server = http.createServer((req, res) => {
  let u = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  if (u.endsWith('/')) u += 'index.html';
  const f = path.join(APP, u);
  if (!f.startsWith(APP) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.statusCode = 404; return res.end('not found'); }
  res.setHeader('content-type', MIME[path.extname(f)] || 'application/octet-stream');
  res.setHeader('cache-control', 'no-store');
  fs.createReadStream(f).pipe(res);
});

const failures = [];
const check = (cond, msg) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${msg}`); if (!cond) failures.push(msg); };

server.listen(0, async () => {
  const origin = `http://localhost:${server.address().port}`;
  const launchArgs = ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'];
  if (VIDEO) launchArgs.push(`--use-file-for-fake-video-capture=${path.resolve(VIDEO)}`);
  const browser = await chromium.launch({ args: launchArgs, executablePath: process.env.MM_CHROMIUM || undefined });
  const ctx = await browser.newContext({ serviceWorkers: 'block', ignoreHTTPSErrors: true, permissions: ['camera'], viewport: { width: 414, height: 896 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, userAgent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36' });
  const external = [];
  const isLocal = (url) => /^(localhost|127\.0\.0\.1)$/.test(url.hostname);
  if (BUNDLED) {
    // The iOS configuration: library and model come from the bundle. Anything that tries to leave the device is blocked and counted.
    await ctx.addInitScript(() => {
      window.MM_CONFIG = { platform: 'ios', freeScans: 3, visionBases: ['vendor/tasks-vision'], modelUrl: 'vendor/face_landmarker.task' };
      // Stand-in for the iOS app's "native" message handler (the store handler is left out so the page behaves as it does before a purchase message arrives).
      window.__nativeMessages = [];
      window.webkit = { messageHandlers: { native: { postMessage: (m) => window.__nativeMessages.push(m) } } };
    });
    await ctx.route((url) => /^https?:$/.test(url.protocol) && !isLocal(url), (route) => { external.push(route.request().url()); route.abort(); });
  } else {
    // The web configuration: serve the vision library (and optionally the model) from local copies so the test does not depend on the network.
    await ctx.route(/https:\/\/(cdn\.jsdelivr\.net|unpkg\.com)\/.*@mediapipe\/tasks-vision@[^/]+\/(.*)$/, (route) => {
      const rel = route.request().url().match(/tasks-vision@[^/]+\/(.*)$/)[1];
      const f = path.join(VISION_DIR, rel);
      if (!fs.existsSync(f)) return route.fulfill({ status: 404, body: 'missing ' + rel });
      route.fulfill({ status: 200, headers: { 'content-type': MIME[path.extname(f)] || 'application/octet-stream', 'access-control-allow-origin': '*' }, body: fs.readFileSync(f) });
    });
    if (MODEL_PATH) await ctx.route(/face_landmarker\.task$/, (route) => route.fulfill({ status: 200, headers: { 'content-type': 'application/octet-stream', 'access-control-allow-origin': '*' }, body: fs.readFileSync(MODEL_PATH) }));
  }
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/INFO: Created TensorFlow Lite|Failed to load resource/.test(m.text())) errors.push('console.error: ' + m.text()); });
  page.on('requestfailed', (r) => errors.push('requestfailed: ' + r.url() + ' ' + (r.failure() && r.failure().errorText)));

  await page.goto(`${origin}/index.html`);
  try {
    await page.waitForFunction(() => /ready/i.test(document.getElementById('model-status').textContent), null, { timeout: 120000 });
    check(true, 'vision library and face model loaded');
  } catch (e) {
    check(false, `vision library and face model loaded (status: "${await page.textContent('#model-status')}")`);
    await browser.close(); server.close(); process.exit(1);
  }
  await page.screenshot({ path: path.join(OUT, '01-welcome.png'), fullPage: true });

  if (VIDEO) {
    await page.click('#btn-open');
    await page.waitForFunction(() => !document.getElementById('view-mirror').hidden && document.getElementById('video').videoWidth > 0, null, { timeout: 30000 });
    await page.waitForFunction(() => !document.getElementById('btn-consult').disabled, null, { timeout: 30000 });
    await page.waitForFunction(() => !/Looking for a face|Asking|Waking/.test(document.getElementById('guidance').textContent), null, { timeout: 30000 });
    const guidance = await page.textContent('#guidance');
    const dots = await page.$$eval('.dot.on', (d) => d.length);
    console.log(`      guidance: "${guidance}"  dots on: ${dots}/5`);
    check(dots >= 1, 'live loop finds the face and reports pose');
    await page.screenshot({ path: path.join(OUT, '02-live.png'), fullPage: true });
    await page.click('#btn-consult');
    await page.waitForFunction(() => !document.getElementById('view-verdict').hidden, null, { timeout: 60000 });
    const r = await page.evaluate(() => { const r = window.__mirror.lastResult; return { score: r.score, tier: r.tier.label, phi: r.groups.phi.score, sym: r.symmetry.score, notes: r.notes.map((n) => n.text), hairline: r.hairline, mm: r.mmPerPx, metrics: r.allMetrics.map((m) => [m.id, +m.measured.toFixed(3), +m.score.toFixed(1)]) }; });
    console.log('      camera verdict:', JSON.stringify(r, null, 1).slice(0, 1500));
    check(r.score > 60 && r.score < 100, `camera verdict rendered with score ${r.score.toFixed(1)} (${r.tier})`);
    check(await page.$$eval('.metric', (m) => m.length) === 15, 'fifteen metric rows rendered');
    check(await page.$eval('.still-wrap canvas', (c) => c.width > 0 && c.height > 0), 'annotated still drawn');
    // Saving the card: the iOS app hands it to the native share sheet; the web downloads a PNG.
    if (BUNDLED) {
      await page.click('#btn-save');
      await page.waitForFunction(() => window.__nativeMessages.length > 0, null, { timeout: 15000 });
      const m = await page.evaluate(() => window.__nativeMessages[0]);
      check(m.type === 'share' && /^mirror-mirror-[\d.]+\.png$/.test(m.filename) && /^data:image\/png;base64,/.test(m.dataUrl) && m.dataUrl.length > 100000 && /out of 100/.test(m.text), `iOS save posts a native share message (${m.filename}, ${Math.round(m.dataUrl.length / 1024)} KB)`);
    } else {
      const [download] = await Promise.all([page.waitForEvent('download', { timeout: 20000 }), page.click('#btn-save')]);
      check(/^mirror-mirror-[\d.]+\.png$/.test(download.suggestedFilename()), `web save downloads a PNG (${download.suggestedFilename()})`);
    }
    await page.click('.metric-head');
    check(await page.$eval('.metric-detail', (d) => !d.hidden && d.textContent.includes('score = 100')), 'tapping a row shows the working');
    check(await page.$$eval('.verdict-hero', (h) => h.length) === 1, 'verdict rendered exactly once');
    await page.screenshot({ path: path.join(OUT, '03-verdict-camera.png'), fullPage: true });
    await (await page.$('.verdict-hero')).screenshot({ path: path.join(OUT, '03a-hero.png') });
    await (await page.$('.still-wrap')).screenshot({ path: path.join(OUT, '03b-still.png') });
    await (await page.$('.panel')).screenshot({ path: path.join(OUT, '03c-panel.png') });
    await (await page.$('.notes')).screenshot({ path: path.join(OUT, '03d-notes.png') });
    await page.click('#btn-again');
  }

  if (PHOTO) {
    await page.waitForSelector('#view-welcome:not([hidden])');
    const input = await page.$('#file-input');
    await input.setInputFiles(path.resolve(PHOTO));
    await page.waitForFunction(() => !document.getElementById('view-verdict').hidden, null, { timeout: 60000 });
    const r = await page.evaluate(() => { const r = window.__mirror.lastResult; return { score: r.score, tier: r.tier.label, hairline: r.hairline && r.hairline.found ? Math.round(r.hairline.pxAbove) : null, notes: r.notes.length }; });
    console.log('      photo verdict:', JSON.stringify(r));
    check(r.score > 60 && r.score < 100, `photo verdict rendered with score ${r.score.toFixed(1)} (${r.tier})`);
    await page.screenshot({ path: path.join(OUT, '04-verdict-photo.png'), fullPage: true });
    await (await page.$('.still-wrap')).screenshot({ path: path.join(OUT, '04b-still.png') });
    const panels = await page.$$('.panel');
    for (let i = 0; i < panels.length; i++) await panels[i].screenshot({ path: path.join(OUT, `04p${i}.png`) });
  }

  // Free readings, then the paywall.
  if (!(await page.$eval('#view-welcome', (v) => !v.hidden))) { await page.click('#btn-again'); }
  await page.waitForSelector('#view-welcome:not([hidden])');
  const plan = await page.textContent('#plan-status');
  console.log(`      plan line: "${plan.trim()}"`);
  check(/free reading/.test(plan), 'welcome shows the free-reading allowance');
  await page.evaluate(() => localStorage.setItem('mm.scans.v1', '3'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  try {
    await page.waitForFunction(() => /No free readings left/.test((document.getElementById('plan-status') || {}).textContent || ''), null, { timeout: 30000 });
  } catch (e) {
    check(false, `after reload the plan line shows no free readings (saw: "${await page.textContent('#plan-status')}", scans=${await page.evaluate(() => localStorage.getItem('mm.scans.v1'))})`);
  }
  await page.click('#btn-open');
  await page.waitForSelector('#view-paywall:not([hidden])', { timeout: 10000 });
  const pw = await page.textContent('#paywall-root');
  check(/\$0\.99/.test(pw) && /Restore purchases/.test(pw) && /Terms of Use/.test(pw) && /renews automatically/.test(pw), 'paywall shows price, auto-renewal terms, restore and legal links');
  await page.screenshot({ path: path.join(OUT, '05-paywall.png'), fullPage: true });
  await page.evaluate(() => window.__mirrorStore.receive({ type: 'purchase', ok: true, entitled: true, price: '$0.99', period: 'month' }));
  await page.waitForSelector('#view-welcome:not([hidden])', { timeout: 10000 });
  check(/Premium/.test(await page.textContent('#plan-status')), 'a store entitlement message unlocks the mirror');
  await page.evaluate(() => localStorage.clear());

  check(errors.length === 0, `no page errors (${errors.length ? errors.join(' | ').slice(0, 800) : 'clean'})`);
  if (BUNDLED) check(external.length === 0, `no request left the device (${external.length ? external.join(', ') : 'every request was served from the bundle'})`);
  await browser.close(); server.close();
  console.log(failures.length ? `\n${failures.length} FAILED` : '\nALL PASSED');
  process.exit(failures.length ? 1 : 0);
});
