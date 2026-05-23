/* ID Delete service worker — minimal offline-capable shell.
   Caches the static frontend so the app loads when the network blips.
   Network-first for API calls so user data is always fresh. */

const CACHE = 'iddelete-v1';
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

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Only handle GETs; let POSTs (login, scan, etc.) pass through untouched.
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Network-first for API + auth so we don't serve stale dashboard data
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => caches.match(req))
    );
    return;
  }

  // Stale-while-revalidate for everything else
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
