"""RTL visual regression checks; use demo mode without writing any data.

Run against the local app: uv run --with playwright python tests/browser_layout.py
"""

from pathlib import Path

from playwright.sync_api import expect, sync_playwright

SHOTS = Path("/tmp/opencode/hesab-layout")


def assert_input_hint_clear(field):
    geometry = field.locator('xpath=ancestor::*[@data-testid="stTextInput"]').evaluate(
        """element => {
            const input = element.querySelector('input').getBoundingClientRect();
            const hint = element.querySelector('[data-testid="InputInstructions"]');
            if (!hint || getComputedStyle(hint).display === 'none') return {overlap: 0};
            const rect = hint.getBoundingClientRect();
            return {overlap: Math.min(input.bottom, rect.bottom) - Math.max(input.top, rect.top)};
        }"""
    )
    assert geometry["overlap"] <= 0, f"Input hint overlaps typed text: {geometry}"


def assert_chips_fit(page):
    failures = page.locator('[data-testid="stButtonGroup"] [role="radiogroup"]').evaluate_all(
        """groups => groups.flatMap(group => {
            const bounds = group.getBoundingClientRect();
            const buttons = [...group.querySelectorAll('button')];
            if (buttons.length === 2 && Math.abs(buttons[0].getBoundingClientRect().top -
                buttons[1].getBoundingClientRect().top) > 1) {
                return [{error: 'Two-option selector should fit on one row'}];
            }
            return buttons.flatMap(button => {
                const rect = button.getBoundingClientRect();
                const p = button.querySelector('p');
                const text = p && p.getBoundingClientRect();
                const fits = rect.left >= bounds.left - .5 && rect.right <= bounds.right + .5;
                const textFits = !text || (text.top >= rect.top && text.bottom <= rect.bottom);
                return fits && textFits ? [] : [{text: button.innerText, fits, textFits}];
            });
        })"""
    )
    assert not failures, f"Clipped selector chips: {failures}"


def assert_badges_fit(page):
    failures = page.locator(".pill, .local-badge").evaluate_all(
        """badges => badges.flatMap(badge => {
            const range = document.createRange();
            range.selectNodeContents(badge);
            const text = range.getBoundingClientRect();
            let parent = badge;
            while (parent && !parent.matches('[data-testid="stMain"]')) {
                const rect = parent.getBoundingClientRect();
                const style = getComputedStyle(parent);
                if (['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowY) &&
                    (text.top < rect.top - 1 || text.bottom > rect.bottom + 1)) {
                    return [{text: badge.innerText, parent: parent.dataset.testid || parent.tagName}];
                }
                parent = parent.parentElement;
            }
            return [];
        })"""
    )
    assert not failures, f"Clipped status badges: {failures}"


def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"]
        )
        for width in [1366, 768, 390]:
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page.goto("http://127.0.0.1:8501", wait_until="networkidle")
            sidebar = page.locator('[data-testid="stSidebar"]')
            if sidebar.get_attribute("data-collapsed") == "true":
                page.get_by_role("button", name="Expand sidebar").click()
            sidebar.get_by_text("حالت نمایشی", exact=False).click()
            expect(page.get_by_text("کل موجودی · تا امروز", exact=True)).to_be_visible()
            if width < 1000 and sidebar.get_attribute("data-collapsed") != "true":
                page.get_by_role("button", name="Collapse sidebar").click()
                expect(sidebar.get_by_text("مدیریت مالی", exact=True)).to_be_hidden()
            page.get_by_role("button", name="ثبت تراکنش", exact=True).click()
            dialog = page.get_by_role("dialog")
            field = dialog.get_by_role("textbox", name="توضیح (اختیاری)", exact=True)
            page.evaluate("document.fonts.ready")
            expect(dialog.locator('[data-testid="stFormSubmitButton"]')).to_be_visible()
            # Measure after Streamlit's dialog entrance/layout animation settles.
            page.wait_for_timeout(400)
            submit = dialog.get_by_role("button", name="ثبت تراکنش", exact=True)
            submit_y = submit.bounding_box()["y"]
            field.fill("متن فارسی و English 123 برای بررسی جای ورودی")
            assert_input_hint_clear(field)
            field.blur()
            new_y = submit.bounding_box()["y"]
            assert abs(new_y - submit_y) < 1, (
                f"Input hints shifted submit button: {submit_y} -> {new_y} at {width}px"
            )
            amount = dialog.get_by_role("textbox", name="مبلغ (تومان)", exact=True)
            amount.fill("1234567890")
            assert_input_hint_clear(amount)
            expect(amount).not_to_have_js_property("value", "")
            assert_chips_fit(dialog)
            page.screenshot(path=str(SHOTS / f"dialog-{width}.png"))
            page.keyboard.press("Escape")
            if sidebar.get_attribute("data-collapsed") == "true":
                page.get_by_role("button", name="Expand sidebar").click()
            sidebar.locator("label").filter(has=page.get_by_role("radio", name="هدف‌ها")).click()
            expect(page.locator(".page-head h1")).to_have_text("هدف‌ها")
            if width < 1000 and sidebar.get_attribute("data-collapsed") != "true":
                page.get_by_role("button", name="Collapse sidebar").click()
            expect(page.locator(".pill").first).to_be_visible()
            assert_badges_fit(page)
            if width < 1000:
                expect(sidebar.get_by_text("امروز ·", exact=False)).to_be_hidden()
            page.screenshot(path=str(SHOTS / f"goals-{width}.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.close()
        browser.close()
    print(f"Input, selector and badge layout checks passed at 1366, 768 and 390px. {SHOTS}")


if __name__ == "__main__":
    main()
