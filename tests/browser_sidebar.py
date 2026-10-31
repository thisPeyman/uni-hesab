"""Read-only sidebar navigation, keyboard and responsive layout checks in demo mode.

Run: uv run --with playwright python tests/browser_sidebar.py
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

SHOTS = Path("/tmp/opencode/hesab-sidebar")


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"]
        )
        for width, height in [(1366, 900), (1366, 680), (390, 844)]:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto("http://127.0.0.1:8501", wait_until="networkidle")
            sidebar = page.locator('[data-testid="stSidebar"]')
            if sidebar.get_attribute("data-collapsed") == "true":
                page.get_by_role("button", name="Expand sidebar").click()
            sidebar.get_by_text("حالت نمایشی", exact=True).click()
            expect(page.locator(".balance-sheet")).to_be_visible()
            navigation = sidebar.get_by_role("radiogroup", name="بخش‌های حساب")
            expect(navigation.get_by_role("radio")).to_have_count(5)
            expect(sidebar.locator(".st-key-sidebar_mode")).to_be_visible()
            page.evaluate("document.fonts.ready")
            page.wait_for_timeout(400)
            geometry = navigation.evaluate("""group => {
                const container = group.closest('[data-testid="stSidebarUserContent"]');
                const bounds = group.getBoundingClientRect();
                return {
                    width: bounds.width,
                    available: container.clientWidth - parseFloat(getComputedStyle(container).paddingLeft)
                        - parseFloat(getComputedStyle(container).paddingRight),
                    rows: [...group.querySelectorAll('label')].map(row => ({
                        width: row.getBoundingClientRect().width,
                        height: row.getBoundingClientRect().height,
                        fits: row.scrollWidth <= row.clientWidth + 1,
                    })),
                };
            }""")
            assert geometry["width"] >= geometry["available"] - 2, geometry
            assert all(
                row["width"] >= geometry["width"] - 2 and row["height"] >= 48 and row["fits"]
                for row in geometry["rows"]
            ), geometry
            # The empty part of a navigation row must be clickable too.
            budget_radio = page.get_by_role("radio", name="بودجه‌ها")
            budget_row = sidebar.locator("label").filter(has=budget_radio)
            budget_row.click(position={"x": 20, "y": 24})
            expect(budget_radio).to_be_checked()
            expect(page.locator(".page-head h1")).to_have_text("بودجه‌ها")
            for name in ["تراکنش‌ها", "بودجه‌ها", "هدف‌ها", "تنظیمات"]:
                radio = page.get_by_role("radio", name=name)
                sidebar.locator("label").filter(has=radio).click()
                expect(radio).to_be_checked()
                expect(page.locator(".page-head h1")).to_have_text(name)
            selected = sidebar.get_by_role("radio", name="تنظیمات")
            selected.focus()
            selected.press("ArrowUp")
            expect(sidebar.get_by_role("radio", name="هدف‌ها")).to_be_checked()
            expect(page.locator(".page-head h1")).to_have_text("هدف‌ها")
            sidebar.screenshot(path=str(SHOTS / f"sidebar-{width}-{height}.png"))
            sidebar.get_by_text("حالت نمایشی", exact=True).scroll_into_view_if_needed()
            sidebar.get_by_text("حالت نمایشی", exact=True).click()
            expect(sidebar.get_by_role("switch", name="حالت نمایشی")).not_to_be_checked()
            expect(
                page.get_by_text(
                    "حالت نمایشی · این اطلاعات ساختگی است و از حساب شخصی شما جداست.", exact=True
                )
            ).to_have_count(0)
            sidebar.locator(".brand").scroll_into_view_if_needed()
            page.get_by_role("button", name="Collapse sidebar").click()
            expect(sidebar.locator(".brand")).to_be_hidden()
            page.get_by_role("button", name="Expand sidebar").click()
            expect(sidebar.get_by_role("radio", name="هدف‌ها")).to_be_checked()
            assert page.locator('[data-testid="stException"]').count() == 0
            page.close()
        browser.close()
    print(f"Sidebar width, navigation, keyboard, mode and collapse checks passed. {SHOTS}")


if __name__ == "__main__":
    main()
