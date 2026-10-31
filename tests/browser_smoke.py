"""Optional rendered-UI check against a running localhost app, using demo only.

Run: uv run --with playwright python tests/browser_smoke.py
Uses the system Chrome. Screenshots go outside the repository.
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

SHOTS = Path("/tmp/opencode/hesab-screenshots")
NOTE = "آزمون موقت مرورگر — حذف پس از بررسی"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome",
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8501", wait_until="networkidle")
        page.get_by_text("حالت نمایشی", exact=False).click()
        expect(page.get_by_text("کل موجودی · تا امروز", exact=True)).to_be_visible()
        expect(page.locator(".js-plotly-plot")).to_be_visible()
        page.screenshot(path=str(SHOTS / "overview.png"), full_page=True)
        alert = page.locator('[data-testid="stAlert"]').first
        assert alert.bounding_box()["y"] >= 60, "Demo banner is hidden behind the header"
        assert page.evaluate("document.fonts.check('16px Vazirmatn')")

        # Actual dialog lifecycle cannot be simulated by AppTest's full reruns.
        page.get_by_role("button", name="ثبت تراکنش", exact=True).click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        dialog.get_by_role("textbox", name="مبلغ (تومان)", exact=True).fill("12345")
        dialog.get_by_role("textbox", name="توضیح (اختیاری)", exact=True).fill(NOTE)
        page.screenshot(path=str(SHOTS / "transaction-dialog.png"))
        dialog.get_by_role("button", name="ثبت تراکنش", exact=True).click()
        expect(page.get_by_text("تراکنش ثبت شد.", exact=True)).to_be_visible()

        sidebar = page.locator('[data-testid="stSidebar"]')
        sidebar.locator("label").filter(has=page.get_by_role("radio", name="تراکنش‌ها")).click()
        search = page.get_by_label("جست‌وجو در توضیح، دسته یا مبلغ", exact=True)
        search.fill(NOTE)
        search.press("Enter")
        expect(page.get_by_text(NOTE, exact=True)).to_be_visible()
        edit_row = page.locator('[data-testid="stHorizontalBlock"]').filter(
            has=page.locator(".ledger-title", has_text=NOTE)
        )
        edit_row.get_by_role("button", name="ویرایش", exact=True).click()
        dialog.get_by_role("textbox", name="مبلغ (تومان)", exact=True).fill("54321")
        dialog.get_by_role("button", name="ذخیره تغییرات", exact=True).click()
        expect(page.get_by_text("تغییرات تراکنش ذخیره شد.", exact=True)).to_be_visible()
        expect(edit_row.locator(".ledger-amount")).to_contain_text("54,321")
        edit_row.get_by_role("button", name="ویرایش", exact=True).click()
        expect(dialog.get_by_role("button", name="حذف تراکنش", exact=True)).to_be_disabled()
        dialog.get_by_text("حذف این تراکنش را تأیید می‌کنم.", exact=True).click()
        dialog.get_by_role("button", name="حذف تراکنش", exact=True).click()
        expect(page.get_by_text("تراکنش حذف شد.", exact=True)).to_be_visible()
        expect(page.get_by_text(NOTE, exact=True)).to_have_count(0)

        for name, shot in [("بودجه‌ها", "budgets"), ("هدف‌ها", "goals"), ("تنظیمات", "settings")]:
            sidebar.locator("label").filter(has=page.get_by_role("radio", name=name)).click()
            expect(page.locator(".page-head h1")).to_have_text(name)
            page.screenshot(path=str(SHOTS / f"{shot}.png"), full_page=True)
            assert page.locator('[data-testid="stException"]').count() == 0

        sidebar.locator("label").filter(has=page.get_by_role("radio", name="نمای کلی")).click()
        expect(page.locator(".page-head h1")).to_have_text("یک نگاه به پول‌هایت")
        # Collapse before resizing; resizing can automatically replace the control.
        collapse = page.locator('[data-testid="stSidebarCollapseButton"] button')
        collapse.click()
        page.wait_for_timeout(600)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(600)
        expect(sidebar).to_be_hidden()
        page.screenshot(path=str(SHOTS / "mobile.png"), full_page=True)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        assert not errors, errors
        browser.close()
    print(f"Chrome smoke check passed. Screenshots: {SHOTS}")


if __name__ == "__main__":
    main()
