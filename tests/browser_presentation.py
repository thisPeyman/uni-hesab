# /// script
# requires-python = ">=3.12"
# dependencies = ["playwright==1.64.1"]
# ///
"""Check the generated deck's progress, navigation and print layout.

Run after building documents: uv run tests/browser_presentation.py
No Streamlit server or financial data is accessed.
"""

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

DECK = Path(__file__).resolve().parent.parent / "docs/output/presentation.html"


def progress_values(page) -> list[float]:
    backgrounds = page.locator("section.slide").evaluate_all("""slides =>
        slides.map(slide => getComputedStyle(slide, '::after').backgroundImage)
    """)
    values = []
    for background in backgrounds:
        stops = re.findall(r"([\d.]+)%", background)
        assert stops, f"Missing percentage in progress gradient: {background}"
        values.append(float(stops[-1]))
    return values


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path="/usr/bin/google-chrome", args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        page.goto(DECK.as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        count = page.locator("section.slide").count()
        assert (
            page.locator(".slide-number").first.evaluate(
                "element => getComputedStyle(element).direction"
            )
            == "ltr"
        ), "Slide counter must not reverse in the RTL layout"
        expected = [round(index / count * 100, 4) for index in range(1, count + 1)]
        for medium in ["screen", "print"]:
            page.emulate_media(media=medium)
            actual = progress_values(page)
            assert all(abs(a - e) < 0.001 for a, e in zip(actual, expected, strict=True)), (
                medium,
                actual,
                expected,
            )
            assert all(a < b for a, b in zip(actual, actual[1:], strict=False))
            assert actual[-1] == 100
        page.emulate_media(media="screen")
        page.goto(DECK.as_uri() + "?present", wait_until="networkidle")
        for key, slide in [
            ("Home", 1),
            ("ArrowLeft", 2),
            ("End", count),
            ("ArrowRight", count - 1),
        ]:
            page.keyboard.press(key)
            active = page.locator("section.slide.active")
            assert active.get_attribute("id") == f"slide-{slide}"
            assert page.locator("section.slide:visible").count() == 1
            assert f"{slide:02d} / {count:02d}" in active.locator(".slide-number").inner_text()
        page.keyboard.press("p")
        assert page.locator("section.slide:visible").count() == count
        overflow = page.locator("section.slide").evaluate_all("""slides =>
            slides.flatMap((slide, index) => {
                const top = slide.getBoundingClientRect().top;
                const content = [...slide.children].filter(child =>
                    !child.matches('.slide-number, .slide-footer'));
                return content.some(child => child.getBoundingClientRect().bottom - top > 664)
                    || slide.scrollHeight > slide.clientHeight + 1 ? [index + 1] : [];
            })
        """)
        assert not overflow, f"Slides overflow the safe area: {overflow}"
        browser.close()
    print(f"All {count} slides: accurate screen/print progress, navigation and safe layout passed.")


if __name__ == "__main__":
    main()
