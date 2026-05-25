/* ID Delete service worker — minimal offline-capable shell.
   - Network-first for HTML so users always get the latest pages.
   - Network-first for /api/ so user data is always fresh.
   - Stale-while-revalidate for static assets (CSS/JS/images). */

const CACHE = 'iddelete-v3';
const SHELL = [
  '/', '/index.html', '/dashboard.html', '/login.html',
  '/signup.html', '/css/styles.css', '/js/app.js', '/js/api.js',
  '/manifest.json', '/icons/icon.svg',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

function isHtmlRequest(req, url) {
  if (req.mode === 'navigate') return true;
  const accept = req.headers.get('accept') || '';
  if (accept.includes('text/html')) return true;
  if (url.pathname.endsWith('.html') || url.pathname === '/') return true;
  return false;
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only handle GETs; let POSTs (login, scan, etc.) pass through untouched.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Never intercept Cloudflare Turnstile (cross-origin captcha challenges).
  if (url.hostname === 'challenges.cloudflare.com') return;

  // Network-first for API + auth so we don't serve stale dashboard data.
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(fetch(req).catch(() => caches.match(req)));
    return;
  }

  // Network-first for HTML so every page load gets the latest deploy.
  if (isHtmlRequest(req, url)) {
    event.respondWith(
      fetch(req).then((resp) => {
        if (resp && resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Stale-while-revalidate for static assets (CSS/JS/images/icons).
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetched = fetch(req).then((resp) => {
        if (resp && resp.ok && resp.type === 'basic') {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put(req, copy));
        }
        return resp;
      }).catch(() => cached);
      return cached || fetched;
    })
  );
});
