#!/usr/bin/env python3
"""Capture CatCam screenshots for the user guide.

The CatCam web server is normally on the LAN. If Chrome cannot reach the Pi
directly (for example because of macOS local-network privacy), tunnel it first:

    ssh -N -L 18080:192.168.1.201:8080 pi@192.168.1.201
    CATCAM_URL=http://127.0.0.1:18080 python scripts/capture_docs_screenshots.py

Screenshots are written to docs/images/.
"""
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("CATCAM_URL", "http://192.168.1.201:8080").rstrip("/")
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "images"
VIEWPORT = {"width": 1440, "height": 1000}


def save(page, name, full_page=True):
    path = OUTPUT_DIR / name
    page.screenshot(path=str(path), full_page=full_page)
    print(f"wrote {path.relative_to(OUTPUT_DIR.parent.parent)}")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
        except Exception:
            browser = playwright.chromium.launch(headless=True)

        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = context.new_page()

        # Dashboard
        page.goto(f"{BASE_URL}/?tab=dashboard", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "document.querySelectorAll('#statsGrid .stat-card').length >= 3",
            timeout=30000,
        )
        page.wait_for_timeout(4500)
        save(page, "dashboard.png")
        page.locator("section.card").filter(has_text="Camera controls").first.screenshot(
            path=str(OUTPUT_DIR / "dashboard-controls.png")
        )
        print("wrote docs/images/dashboard-controls.png")

        # Settings
        page.goto(f"{BASE_URL}/?tab=settings", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector('[data-page="settings"]:not([hidden])', timeout=30000)
        page.wait_for_timeout(3500)
        save(page, "settings.png")
        page.locator("section.setting-group").filter(
            has_text="Camera mounting & image orientation"
        ).first.screenshot(path=str(OUTPUT_DIR / "settings-orientation.png"))
        print("wrote docs/images/settings-orientation.png")
        page.locator("section.setting-group").filter(
            has_text="Motion detection"
        ).first.screenshot(path=str(OUTPUT_DIR / "settings-motion.png"))
        print("wrote docs/images/settings-motion.png")

        # Gallery and the first burst detail
        page.goto(f"{BASE_URL}/gallery", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_selector(".burst", timeout=30000)
        page.wait_for_timeout(3000)
        save(page, "gallery.png")
        event_href = page.locator('.burst a[href^="/event?"]').first.get_attribute("href")
        if event_href:
            page.goto(f"{BASE_URL}{event_href}", wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("#photoGrid img", timeout=30000)
            page.wait_for_timeout(3000)
            save(page, "event-detail.png")

        # Bird Activity
        page.goto(f"{BASE_URL}/bird-activity", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "document.querySelector('#total') && document.querySelector('#total').textContent.trim() !== '—'",
            timeout=30000,
        )
        page.wait_for_timeout(3000)
        save(page, "bird-activity.png")

        # Phone-sized dashboard
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=1, is_mobile=True
        )
        mobile_page = mobile.new_page()
        mobile_page.goto(f"{BASE_URL}/?tab=dashboard", wait_until="domcontentloaded", timeout=60000)
        mobile_page.wait_for_timeout(4500)
        save(mobile_page, "dashboard-mobile.png")
        mobile.close()

        context.close()
        browser.close()


if __name__ == "__main__":
    main()
