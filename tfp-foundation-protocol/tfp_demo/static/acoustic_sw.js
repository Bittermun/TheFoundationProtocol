// SPDX-License-Identifier: Apache-2.0
// Coherent, atomically versioned offline Service Worker for TFP Acoustic Receiver.
// Prevents partial updates from mixing incompatible HTML, demodulator JS, and config assets.

const CACHE_VERSION = "tfp-acoustic-receiver-v1";
const REQUIRED_ASSETS = [
  "./acoustic_receiver.html",
  "./acoustic_stream.js",
  "./receiver_config.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      // Fetch all required assets first. If any single asset fails, abort install
      // so an existing coherent cache is never partially overwritten.
      const fetchedEntries = await Promise.all(
        REQUIRED_ASSETS.map(async (assetUrl) => {
          const req = new Request(assetUrl, { cache: "no-cache" });
          const resp = await fetch(req);
          if (!resp || !resp.ok) {
            throw new Error(`Atomic offline cache abort: failed to fetch ${assetUrl} (status ${resp ? resp.status : "network_error"})`);
          }
          return { assetUrl, resp: resp.clone() };
        })
      );

      const cache = await caches.open(CACHE_VERSION);
      for (const { assetUrl, resp } of fetchedEntries) {
        await cache.put(assetUrl, resp);
      }
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.map((key) => {
          if (key.startsWith("tfp-acoustic-receiver-") && key !== CACHE_VERSION) {
            return caches.delete(key);
          }
          return Promise.resolve();
        })
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;

  event.respondWith(
    (async () => {
      const url = new URL(event.request.url);
      const cache = await caches.open(CACHE_VERSION);

      // Normalize root/alias paths to ./acoustic_receiver.html
      let lookupPath = null;
      if (
        url.pathname.endsWith("/") ||
        url.pathname.endsWith("/receiver") ||
        url.pathname.endsWith("/index.html") ||
        url.pathname.endsWith("/acoustic_receiver.html")
      ) {
        lookupPath = "./acoustic_receiver.html";
      } else if (url.pathname.endsWith("/acoustic_stream.js")) {
        lookupPath = "./acoustic_stream.js";
      } else if (url.pathname.endsWith("/receiver_config.json")) {
        // Network-first for receiver_config.json when online to pick up key provisioning,
        // with cached fallback when offline.
        try {
          const fresh = await fetch(event.request);
          if (fresh && fresh.ok) {
            await cache.put("./receiver_config.json", fresh.clone());
            return fresh;
          }
        } catch (_) {
          // Offline fallback below
        }
        lookupPath = "./receiver_config.json";
      }

      if (lookupPath) {
        const cachedResp = await cache.match(lookupPath);
        if (cachedResp) return cachedResp;
      }

      const directCached = await cache.match(event.request);
      if (directCached) return directCached;

      return fetch(event.request);
    })()
  );
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "VERIFY_OFFLINE_CACHE") {
    event.waitUntil(
      (async () => {
        const cache = await caches.open(CACHE_VERSION);
        const checks = await Promise.all(
          REQUIRED_ASSETS.map(async (assetUrl) => Boolean(await cache.match(assetUrl)))
        );
        const complete = checks.every(Boolean);
        if (event.source && event.source.postMessage) {
          event.source.postMessage({
            type: "OFFLINE_CACHE_STATUS",
            cacheVersion: CACHE_VERSION,
            complete,
            requiredAssets: REQUIRED_ASSETS
          });
        }
      })()
    );
  }
});
