// Hikarin Studio — installable app shell.
// Network-first for same-origin GETs (fresh deploys always win when online),
// cache fallback when the network is gone. Project data APIs are NOT cached:
// a stale story file is worse than an honest error.

const CACHE = 'hikarin-shell-v1';

const SHELL = [
  '/',
  '/index.html',
  '/play.html',
  '/studio.css',
  '/studio.js',
  '/assets.js',
  '/play.css',
  '/play.js',
  '/manifest.webmanifest',
  '/favicon.ico',
  '/apple-touch-icon.png',
  '/icon-192.png',
  '/icon-512.png',
  '/icon-maskable-512.png',
  '/vendor/hikarin-vn-viewer.umd.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(SHELL))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/')) return; // never serve stale project state

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      })
      .catch(() => caches.match(request, { ignoreSearch: true }))
  );
});
