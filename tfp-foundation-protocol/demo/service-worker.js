/**
 * TFP Demo Service Worker - Offline-first PWA support.
 *
 * Strategy:
 *   - Static assets (/,  /manifest.json): cache-first
 *   - Content retrieval (/api/get/*): network-first, cache on success for offline playback
 *   - Mutating API calls (/api/publish, /api/earn, /api/enroll): network-only (never cached)
 */

const CACHE_NAME = 'tfp-demo-v1';

const STATIC_ASSETS = ['/', '/manifest.json'];

// ---------------------------------------------------------------------------
// Install: pre-cache static assets
// ---------------------------------------------------------------------------
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// ---------------------------------------------------------------------------
// Activate: remove stale caches from previous versions
// ---------------------------------------------------------------------------
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
      )
  );
  self.clients.claim();
});

// ---------------------------------------------------------------------------
// Fetch: route requests to the correct strategy
// ---------------------------------------------------------------------------
self.addEventListener('fetch', (event) => {
  const { pathname } = new URL(event.request.url);

  if (
    pathname.startsWith('/api/publish') ||
    pathname.startsWith('/api/earn') ||
    pathname.startsWith('/api/enroll')
  ) {
    // Mutations: always go to the network; never cache responses
    event.respondWith(fetch(event.request));
  } else if (pathname.startsWith('/api/get/')) {
    // Content retrieval: network-first, cache successful responses for offline playback
    event.respondWith(networkFirstThenCache(event.request));
  } else {
    // Static assets and read-only API (/api/content, /health): cache-first
    event.respondWith(cacheFirstThenNetwork(event.request));
  }
});

// ---------------------------------------------------------------------------
// Strategy helpers
// ---------------------------------------------------------------------------

async function cacheFirstThenNetwork(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const cache = await caches.open(CACHE_NAME);
    cache.put(request, response.clone());
  }
  return response;
}

async function networkFirstThenCache(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline', cached: false }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
