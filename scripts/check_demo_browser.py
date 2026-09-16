# SPDX-License-Identifier: Apache-2.0
"""Exercise the real local demo in Chromium; no persistent user data is used."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from tfp_cli.smoke import demo_server  # noqa: E402


def check_browser() -> dict:
    output = ROOT / "output" / "playwright"
    output.mkdir(parents=True, exist_ok=True)
    checks = []
    errors = []
    with demo_server() as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1100}, accept_downloads=True)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect(page.get_by_role("button", name="Try a round trip ↗")).to_be_enabled()
        expect(page.locator(".note-card")).to_have_count(3)
        page.evaluate("() => navigator.serviceWorker.ready")
        page.reload()
        expect(page.get_by_role("button", name="Try a round trip ↗")).to_be_enabled()
        page.screenshot(path=str(output / "commons-desktop.png"), full_page=True)
        checks.append("packaged assets and three real sample notes")

        page.get_by_role("button", name="Try a round trip ↗").click()
        expect(page.get_by_role("dialog")).to_be_visible()
        expect(page.locator("#reader-status")).to_contain_text("Round trip verified")
        page.keyboard.press("Escape")
        page.get_by_role("link", name="Your node", exact=True).click()
        expect(page.locator("#stat-credits")).to_have_text("9")
        page.reload()
        expect(page.locator("#stat-credits")).to_have_text("9")
        checks.append("round trip spends one credit; refresh preserves balance")

        page.get_by_role("link", name="Publish a note", exact=True).click()
        title = '<img src=x onerror="window.injected=true">'
        body = "A browser-tested note.\nPlain text: café, 水, 🌱.\n<script>window.injected=true</script>"
        page.get_by_label("Title", exact=True).fill(title)
        page.get_by_label("Your note", exact=True).fill(body)
        page.get_by_label("Tags", exact=True).fill("browser-check, community")
        page.reload()
        expect(page.get_by_label("Your note", exact=True)).to_have_value(body)
        expect(page.get_by_role("button", name="Publish note ↗", exact=True)).to_be_enabled()
        checks.append("draft survives reload")

        page.route("**/api/publish", lambda route: route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Test server unavailable"})))
        page.get_by_role("button", name="Publish note ↗", exact=True).click()
        expect(page.locator("#notice")).to_have_text("Test server unavailable")
        expect(page.get_by_label("Your note", exact=True)).to_have_value(body)
        expect(page.get_by_role("button", name="Publish note ↗", exact=True)).to_be_enabled()
        page.unroute("**/api/publish")
        checks.append("failed publish retains draft and enables retry")

        page.get_by_role("button", name="Publish note ↗", exact=True).click()
        expect(page.locator("#publish-result")).to_be_visible()
        page.get_by_role("button", name="Read your note", exact=True).click()
        expect(page.locator("#reader-text")).to_have_text(body)
        expect(page.locator("#reader-title")).to_have_text(title)
        assert page.evaluate("() => window.injected") is None
        with page.expect_download() as download_event:
            page.get_by_role("button", name="Save as text", exact=True).click()
        assert Path(download_event.value.path()).read_text(encoding="utf-8") == body
        page.keyboard.press("Escape")
        checks.append("publish and download preserve UTF-8; HTML stays inert")

        page.get_by_role("link", name="Content library", exact=False).click()
        page.get_by_role("searchbox", name="Find an exact tag").fill("browser-check")
        page.get_by_role("button", name="Search tags", exact=True).click()
        expect(page.locator(".note-card")).to_have_count(1)
        expect(page.locator(".note-card h3")).to_have_text(title)
        page.get_by_role("searchbox", name="Find an exact tag").fill("no-such-tag")
        page.get_by_role("button", name="Search tags", exact=True).click()
        expect(page.locator(".empty")).to_contain_text("No notes with this tag")
        checks.append("tag filtering and empty state")

        page.get_by_role("button", name="All notes", exact=True).click()
        expect(page.get_by_role("button", name="Read " + title, exact=True)).to_be_visible()
        context.set_offline(True)
        page.get_by_role("button", name="Read " + title, exact=True).click()
        expect(page.locator("#reader-status")).to_contain_text("Saved copy", timeout=25000)
        expect(page.locator("#reader-text")).to_have_text(body)
        page.keyboard.press("Escape")
        context.set_offline(False)
        expect(page.get_by_role("button", name="Try a round trip ↗")).to_be_enabled()
        checks.append("offline reader uses a labeled saved copy and reconnects")

        page.set_viewport_size({"width": 390, "height": 844})
        for view in ("library", "publish", "node", "about"):
            page.goto(base + "/#" + view)
            expect(page.locator("#view-" + view)).to_be_visible()
            assert page.evaluate("() => document.documentElement.scrollWidth <= innerWidth"), view
        page.goto(base)
        expect(page.locator(".note-card")).to_have_count(5)
        page.screenshot(path=str(output / "commons-mobile.png"), full_page=True)
        checks.append("four views fit a 390px mobile viewport")
        assert not errors, errors
        browser.close()
    return {"passed": True, "checks": checks, "screenshots": str(output)}


if __name__ == "__main__":
    print(json.dumps(check_browser(), indent=2))
