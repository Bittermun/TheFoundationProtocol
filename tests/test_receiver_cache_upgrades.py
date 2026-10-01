# SPDX-License-Identifier: Apache-2.0
"""Real Chromium service-worker lifecycle and immutable offline-release regressions."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading

import pytest

sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
WORKER = Path(__file__).resolve().parents[1] / "tfp-foundation-protocol/tfp_demo/static/acoustic_sw.js"
ASSETS = ("acoustic_receiver.html", "acoustic_stream.js", "acoustic_worklet.js",
          "receiver_config.json", "vendor/tfp_crypto.js")


@pytest.fixture
def release_browser():
    # Assets intentionally carry release labels so mixed releases are observable.
    # Only Cache.put failure is injected; install, activation, fetch and storage
    # all run through Chromium and the unmodified production worker handlers.
    state = {"release": "old", "fail_put": False, "worker_revision": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = self.path.split("?", 1)[0].lstrip("/")
            if path == "acoustic_sw.js":
                source = WORKER.read_text(encoding="utf-8")
                source = re.sub(r'const CACHE_VERSION = "[^"]+";',
                                f'const CACHE_VERSION = "tfp-acoustic-receiver-{state["release"]}";', source)
                if state["fail_put"]:
                    source = """
const realPut = Cache.prototype.put;
let puts = 0;
Cache.prototype.put = function(...args) {
  if (++puts === 3) return Promise.reject(new DOMException('Injected quota failure', 'QuotaExceededError'));
  return realPut.apply(this, args);
};
""" + source
                body = (source + f'\n// server revision {state["worker_revision"]}').encode()
                content_type = "text/javascript"
            elif path in ASSETS:
                body = f'{state["release"]}:{path}'.encode()
                content_type = "text/html" if path.endswith(".html") else "text/plain"
            else:
                body = b"<!doctype html><title>Worker lifecycle harness</title>"
                content_type = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        url = f"http://127.0.0.1:{server.server_port}/acoustic_receiver.html"
        page.goto(url)
        page.evaluate("async () => { await navigator.serviceWorker.register('./acoustic_sw.js'); await navigator.serviceWorker.ready; }")
        page.reload()
        page.wait_for_function("navigator.serviceWorker.controller !== null")
        yield state, context, page, url
        context.close()
        browser.close()
    server.shutdown()
    server.server_close()
    thread.join()


def update_worker(page):
    return page.evaluate("""async () => {
      const registration = await navigator.serviceWorker.getRegistration();
      return new Promise(async (resolve, reject) => {
        registration.addEventListener('updatefound', () => {
          const installing = registration.installing;
          installing.addEventListener('statechange', () => {
            if (['installed', 'redundant'].includes(installing.state)) resolve(installing.state);
          });
        }, {once: true});
        try { await registration.update(); } catch (error) { reject(error); }
      });
    }""")


def fetch_assets(page):
    return page.evaluate("""async paths => Object.fromEntries(await Promise.all(paths.map(async path =>
      [path, await (await fetch('./' + path)).text()]
    )))""", list(ASSETS))


def cache_bytes(page, name):
    return page.evaluate("""async name => {
      const cache = await caches.open(name);
      return Object.fromEntries(await Promise.all((await cache.keys()).map(async request =>
        [new URL(request.url).pathname, await (await cache.match(request)).text()])));
    }""", name)


def test_failed_upgrade_preserves_old_bytes_and_removes_partial_cache(release_browser):
    state, context, page, url = release_browser
    before = cache_bytes(page, "tfp-acoustic-receiver-old")
    state.update(release="new", fail_put=True)
    assert update_worker(page) == "redundant"
    assert cache_bytes(page, "tfp-acoustic-receiver-old") == before
    assert page.evaluate("caches.keys()") == ["tfp-acoustic-receiver-old"]
    context.set_offline(True)
    page.reload()
    assert page.locator("body").inner_text() == "old:acoustic_receiver.html"
    assert fetch_assets(page) == {path: f"old:{path}" for path in ASSETS}


def test_upgrade_waits_for_old_clients_then_cold_reopens_complete_new_release(release_browser):
    state, context, page, url = release_browser
    state["release"] = "new"
    assert update_worker(page) == "installed"
    # A lazy worklet/config load in the old page must still be from its release.
    assert fetch_assets(page) == {path: f"old:{path}" for path in ASSETS}
    assert page.evaluate("async () => Boolean((await navigator.serviceWorker.getRegistration()).waiting)")
    # Keep an out-of-scope observer open while closing the last controlled tab.
    observer = context.new_page()
    page.close()
    # The new worker's activation removes only the old release cache.
    observer.goto(url)
    observer.wait_for_function("""async () => {
      const r = await navigator.serviceWorker.getRegistration();
      return r.active && r.active.state === 'activated' && !r.waiting;
    }""")
    context.set_offline(True)
    observer.close()
    reopened = context.new_page()
    reopened.goto(url)
    assert reopened.locator("body").inner_text() == "new:acoustic_receiver.html"
    assert fetch_assets(reopened) == {path: f"new:{path}" for path in ASSETS}
    assert reopened.evaluate("caches.keys()") == ["tfp-acoustic-receiver-new"]
    status = reopened.evaluate("""() => new Promise(resolve => {
      navigator.serviceWorker.addEventListener('message', event => resolve(event.data), {once: true});
      navigator.serviceWorker.controller.postMessage({type: 'VERIFY_OFFLINE_CACHE'});
    })""")
    assert status["type"] == "OFFLINE_CACHE_STATUS"
    assert status["complete"] is True
    assert "./vendor/tfp_crypto.js" in status["requiredAssets"]


def test_same_release_reinstallation_does_not_overwrite_complete_cache(release_browser):
    state, context, page, url = release_browser
    before = cache_bytes(page, "tfp-acoustic-receiver-old")
    # Even a redeployed worker under an unchanged release id cannot corrupt the
    # complete existing cache when writes fail partway through installation.
    state.update(fail_put=True, worker_revision=1)
    assert update_worker(page) == "installed"
    assert cache_bytes(page, "tfp-acoustic-receiver-old") == before


def test_retry_replaces_incomplete_staging_without_touching_active_release(release_browser):
    state, context, page, url = release_browser
    before = cache_bytes(page, "tfp-acoustic-receiver-old")
    page.evaluate("""async () => {
      const partial = await caches.open('tfp-acoustic-receiver-new');
      await partial.put('./acoustic_receiver.html', new Response('incomplete'));
    }""")
    state["release"] = "new"
    assert update_worker(page) == "installed"
    assert cache_bytes(page, "tfp-acoustic-receiver-old") == before
    assert fetch_assets(page) == {path: f"old:{path}" for path in ASSETS}
    staged = cache_bytes(page, "tfp-acoustic-receiver-new")
    assert len(staged) == len(ASSETS)
    assert all(value.startswith("new:") for value in staged.values())
