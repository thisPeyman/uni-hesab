# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.64.1"]
# ///
"""Capture read-only, demo-only screenshots for the university documents.

Run with the app already running: uv run docs/capture_screenshots.py
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1.5)
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        sidebar = page.locator('[data-testid="stSidebar"]')
        sidebar.get_by_text("حالت نمایشی", exact=True).click()
        expect(page.locator(".balance-sheet")).to_be_visible()
        for name, filename in [
            ("نمای کلی", "overview"),
            ("تراکنش‌ها", "transactions"),
            ("بودجه‌ها", "budgets"),
            ("هدف‌ها", "goals"),
            ("تنظیمات", "settings"),
        ]:
            radio = page.get_by_role("radio", name=name)
            sidebar.locator("label").filter(has=radio).click()
            expect(radio).to_be_checked()
            expect(page.locator('[data-testid="stException"]')).to_have_count(0)
            page.evaluate("document.activeElement?.blur()")
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(700)
            page.screenshot(path=str(ASSETS / f"{filename}.png"))
        radio = page.get_by_role("radio", name="تراکنش‌ها")
        sidebar.locator("label").filter(has=radio).click()
        page.get_by_role("button", name="ثبت تراکنش", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(400)
        dialog.screenshot(path=str(ASSETS / "transaction-dialog.png"))
        browser.close()
    print(f"Saved six demo screenshots to {ASSETS}; no financial data was changed.")


if __name__ == "__main__":
    main()
