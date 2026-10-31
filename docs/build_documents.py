# /// script
# requires-python = ">=3.12"
# dependencies = ["markdown-it-py==4.2.0", "playwright==1.64.1"]
# ///
"""Build the Persian report and slide deck from editable Markdown.

Run: uv run docs/build_documents.py
Only documentation outputs are written. No app/database dependency is imported.
"""

import argparse
import base64
import json
import mimetypes
import re
import shutil
from html import escape
from pathlib import Path

from markdown_it import MarkdownIt
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")


def without_frontmatter(text: str) -> str:
    return re.sub(r"\A---\n.*?\n---\n", "", text, count=1, flags=re.S)


def metadata_replace(text: str, metadata: dict) -> str:
    for key, value in metadata.items():
        text = text.replace("{{" + key + "}}", escape(str(value)))
    remaining = re.findall(r"\{\{([^}]+)\}\}", text)
    if remaining:
        raise ValueError(f"Unresolved document fields: {remaining}")
    return text


def data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def embed_css(path: Path) -> str:
    return re.sub(
        r"url\(['\"]?([^)'\"]+)['\"]?\)",
        lambda match: f'url("{data_url((path.parent / match[1]).resolve())}")',
        path.read_text(),
    )


def embed_images(content: str, source_dir: Path) -> str:
    return re.sub(
        r'src="([^\"]+)"',
        lambda match: f'src="{data_url((source_dir / match[1]).resolve())}"',
        content,
    )


def html_document(title: str, content: str, css: str, script: str = "") -> str:
    return (
        '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{css}</style></head><body>"
        f"{content}{script}</body></html>"
    )


DECK_SCRIPT = """
<button class="deck-control prev" aria-label="اسلاید قبلی">قبلی →</button>
<button class="deck-control next" aria-label="اسلاید بعدی">← بعدی</button>
<script>
const slides = [...document.querySelectorAll('section.slide')];
let index = Math.max(0, Math.min(slides.length - 1,
    parseInt(location.hash.slice(1), 10) - 1 || 0));
const presentation = new URLSearchParams(location.search).has('present');
function show(next) {
    index = Math.max(0, Math.min(slides.length - 1, next));
    slides.forEach((slide, n) => slide.classList.toggle('active', n === index));
    history.replaceState(null, '', '#' + (index + 1));
    if (!document.body.classList.contains('presenting'))
        slides[index].scrollIntoView({block: 'center'});
}
function resize() {
    document.body.style.setProperty('--deck-scale',
        Math.min(innerWidth / 1280, innerHeight / 720));
}
if (presentation) document.body.classList.add('presenting');
resize(); addEventListener('resize', resize); show(index);
document.querySelector('.prev').onclick = () => show(index - 1);
document.querySelector('.next').onclick = () => show(index + 1);
document.addEventListener('keydown', event => {
    if (['ArrowLeft','ArrowRight','PageDown','PageUp',' ','Home','End','f','F','p','P','Escape'].includes(event.key))
        event.preventDefault();
    if (['ArrowLeft','PageDown',' '].includes(event.key)) show(index + 1);
    if (['ArrowRight','PageUp'].includes(event.key)) show(index - 1);
    if (event.key === 'Home') show(0);
    if (event.key === 'End') show(slides.length - 1);
    if (['p','P'].includes(event.key)) {
        document.body.classList.toggle('presenting'); resize(); show(index);
    }
    if (['f','F'].includes(event.key)) {
        if (!document.fullscreenElement) document.documentElement.requestFullscreen();
        else document.exitFullscreen();
    }
    if (event.key === 'Escape') document.body.classList.remove('presenting');
});
</script>
"""


def build_sources() -> int:
    metadata = json.loads((ROOT / "project.json").read_text())
    OUTPUT.mkdir(exist_ok=True)
    report = metadata_replace((ROOT / "report/REPORT.md").read_text(), metadata)
    report_md = without_frontmatter(report).replace(
        'href="report.css"', 'href="../report/report.css"'
    )
    (OUTPUT / "project-report.md").write_text(report_md)
    body = without_frontmatter(report)
    body = re.sub(r'<link rel="stylesheet"[^>]+>', "", body)
    body = embed_images(MARKDOWN.render(body), ROOT / "report")
    (OUTPUT / "project-report.html").write_text(
        html_document("حساب | گزارش کامل پروژه", body, embed_css(ROOT / "report/report.css"))
    )
    slides = metadata_replace((ROOT / "presentation/SLIDES.md").read_text(), metadata)
    (OUTPUT / "presentation.md").write_text(slides)
    pieces = re.split(r"\n---\s*\n", without_frontmatter(slides).strip())
    sections, notes = [], ["# راهنمای ارائه و یادداشت سخنران\n"]
    for index, source in enumerate(pieces, 1):
        layout = re.search(r"<!-- slide(?:: ([\w -]+))? -->", source)
        classes = layout[1] if layout and layout[1] else ""
        note = re.search(r"<!-- notes: (.*?) -->", source, flags=re.S)
        source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
        title = re.search(r"^# (.+)$", source, flags=re.M)
        slide_title = title[1] if title else "معرفی حساب"
        rendered = embed_images(MARKDOWN.render(source), ROOT / "presentation")
        sections.append(
            f'<section class="slide {classes}" id="slide-{index}" '
            f'style="--slide-progress:{index / len(pieces) * 100:.4f}%" '
            f'aria-label="اسلاید {index}: {escape(slide_title)}">{rendered}'
            f'<div class="slide-number">{index:02d} / {len(pieces):02d}</div>'
            '<div class="slide-footer">حساب · مدیریت مالی شخصی</div></section>'
        )
        notes.append(f"## اسلاید {index} — {slide_title}\n\n{note[1] if note else ''}\n")
    (ROOT / "presentation/SPEAKER_NOTES.md").write_text("\n".join(notes))
    (OUTPUT / "presentation.html").write_text(
        html_document(
            "حساب | ارائه پروژه",
            "\n".join(sections),
            embed_css(ROOT / "presentation/slides.css"),
            DECK_SCRIPT,
        )
    )
    return len(pieces)


def export_pdfs(chrome: str, slide_count: int) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=chrome, headless=True, args=["--no-sandbox"]
        )
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for name in ["project-report", "presentation"]:
            page.goto((OUTPUT / f"{name}.html").as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.wait_for_function(
                "[...document.images].every(i => i.complete && i.naturalWidth > 0)"
            )
            if name == "presentation":
                assert page.locator("section.slide").count() == slide_count
                overflow = page.locator("section.slide").evaluate_all("""slides =>
                    slides.map((s, i) => ({slide: i + 1,
                        overflow: s.scrollHeight > s.clientHeight + 1,
                        bottom: Math.max(...[...s.children]
                            .filter(c => !c.classList.contains('slide-number') && !c.classList.contains('slide-footer'))
                            .map(c => c.getBoundingClientRect().bottom - s.getBoundingClientRect().top))
                    })).filter(s => s.overflow || s.bottom > 664)
                """)
                if overflow:
                    raise ValueError(f"Slide content enters footer or overflows: {overflow}")
                page.pdf(
                    path=str(OUTPUT / f"{name}.pdf"),
                    width="1280px",
                    height="720px",
                    print_background=True,
                    prefer_css_page_size=True,
                    tagged=True,
                    outline=True,
                )
            else:
                page.pdf(
                    path=str(OUTPUT / f"{name}.pdf"),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    tagged=True,
                    outline=True,
                    display_header_footer=True,
                    header_template="<span></span>",
                    footer_template=(
                        '<div style="width:100%;font-family:Tahoma;font-size:8px;'
                        'color:#68796f;padding:0 16mm;display:flex;justify-content:space-between">'
                        '<span>Hesab | Project report</span><span class="pageNumber"></span></div>'
                    ),
                )
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-only", action="store_true", help="Skip PDF export")
    parser.add_argument("--chrome", help="Path to Chrome/Chromium executable")
    args = parser.parse_args()
    count = build_sources()
    if not args.html_only:
        chrome = args.chrome or shutil.which("google-chrome") or shutil.which("chromium")
        if not chrome:
            parser.error("Chrome not found; use --chrome PATH or --html-only")
        export_pdfs(chrome, count)
    print(f"Built report and {count}-slide presentation in {OUTPUT}")


if __name__ == "__main__":
    main()
