/* Mirror Mirror service worker.
   Shell files: cache first, refreshed in the background.
   Face model and vision library: cache first (they are versioned by URL), so the
   mirror keeps working offline once it has been opened once. */
const VERSION = 'mm-v4';
const SHELL = [
  './', './index.html', './methodology.html', './privacy.html', './terms.html', './manifest.webmanifest',
  './css/style.css', './js/app.js', './js/ui.js', './js/phi.js', './js/geometry.js', './js/landmarks.js',
  './js/pose.js', './js/overlay.js', './js/norms.js', './js/hairline.js', './js/paywall.js', './icons/icon.svg', './licenses.html',
  './css/fonts/PlayfairDisplay-Roman-latin.woff2', './css/fonts/PlayfairDisplay-Italic-latin.woff2',
  './css/fonts/JosefinSans-Roman-latin.woff2', './css/fonts/JosefinSans-Italic-latin.woff2'
];
const HEAVY_HOSTS = ['cdn.jsdelivr.net', 'unpkg.com', 'storage.googleapis.com'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const sameOrigin = url.origin === self.location.origin;
  const heavy = HEAVY_HOSTS.includes(url.hostname);
  if (!sameOrigin && !heavy) return;

  event.respondWith((async () => {
    const cache = await caches.open(VERSION);
    const cached = await cache.match(req);
    const network = fetch(req).then((res) => {
      if (res && (res.ok || res.type === 'opaque')) cache.put(req, res.clone());
      return res;
    }).catch(() => undefined);
    if (cached) {
      if (sameOrigin) network.catch(() => {}); // refresh shell quietly
      return cached;
    }
    const res = await network;
    if (res) return res;
    if (req.mode === 'navigate') return cache.match('./index.html');
    return new Response('', { status: 504, statusText: 'offline' });
  })());
});
