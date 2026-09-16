/* SPDX-License-Identifier: Apache-2.0 */
// Only the application shell and successfully retrieved notes are cached.
// Status, balances, listings, errors, and mutations always use the network.
const CACHE_NAME = 'tfp-demo-v2';
const SHELL = ['/', '/manifest.json', '/assets/app.css', '/assets/app.js', '/assets/icon.svg'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('tfp-demo-') && key !== CACHE_NAME).map(key => caches.delete(key))
  )).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin) return;
  if (SHELL.includes(url.pathname)) {
    event.respondWith(shell(event.request));
  } else if (url.pathname.startsWith('/api/get/') && !url.searchParams.has('stream')) {
    event.respondWith(note(event.request));
  }
});
async function shell(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(request, response.clone());
    return response;
  } catch {
    return await cache.match(request) || new Response('Offline. Reconnect to load Foundation.', {status: 503});
  }
}
async function note(request) {
  const cache = await caches.open(CACHE_NAME);
  try {
    const response = await fetch(request);
    if (response.status === 200 && response.headers.get('content-type')?.includes('application/json')) {
      await cache.put(request, response.clone());
    }
    return response;
  } catch {
    const saved = await cache.match(request);
    if (saved) {
      const headers = new Headers(saved.headers);
      headers.set('X-TFP-Offline', '1');
      return new Response(await saved.arrayBuffer(), {status: 200, headers});
    }
    return new Response(JSON.stringify({detail: 'This note is not saved in this browser. Reconnect to retrieve it.'}), {
      status: 503, headers: {'Content-Type': 'application/json'}
    });
  }
}
