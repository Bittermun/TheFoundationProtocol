// SPDX-License-Identifier: Apache-2.0
// Coherent, atomically versioned offline Service Worker for TFP Acoustic Receiver.
// Prevents partial updates from mixing incompatible HTML, demodulator JS, and config assets.

// Bump this release id whenever any required asset changes. A published cache
// is immutable, including configuration and bundled cryptographic code.
const CACHE_VERSION = "tfp-acoustic-receiver-v2";
const REQUIRED_ASSETS = [
  "./acoustic_receiver.html",
  "./acoustic_stream.js",
  "./acoustic_worklet.js",
  "./vendor/tfp_crypto.js",
  "./receiver_config.json"
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      // A browser may reinstall a worker without a release change. Never write
      // into a published cache, even if the server now returns different bytes.
      if (await caches.has(CACHE_VERSION)) {
        const existing = await caches.open(CACHE_VERSION);
        const complete = await Promise.all(REQUIRED_ASSETS.map(async asset => Boolean(await existing.match(asset))));
        if (complete.every(Boolean)) return;
        // A previous install can be terminated after Cache.put but before its
        // catch handler runs. Discard only this incomplete staging release.
        await caches.delete(CACHE_VERSION);
      }
      // Fetch first, then stage in a cache unique to this release. A failed put
      // (for example quota exhaustion) must remove all partial staging bytes.
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

      try {
        const cache = await caches.open(CACHE_VERSION);
        for (const { assetUrl, resp } of fetchedEntries) {
          await cache.put(assetUrl, resp);
        }
      } catch (error) {
        await caches.delete(CACHE_VERSION);
        throw error;
      }
      // Do not skipWaiting: existing pages may still lazily load their worklet.
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
      // Normal activation waits for the previous worker's clients to close.
      // Do not claim uncontrolled pages that loaded another release online.
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
      } else if (url.pathname.endsWith("/acoustic_worklet.js")) {
        lookupPath = "./acoustic_worklet.js";
      } else if (url.pathname.endsWith("/vendor/tfp_crypto.js")) {
        lookupPath = "./vendor/tfp_crypto.js";
      } else if (url.pathname.endsWith("/receiver_config.json")) {
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
