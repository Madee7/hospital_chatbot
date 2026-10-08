"""Convert a docs/*.md guide to docs/pdf/*.pdf via headless Chrome.

Usage:
    python docs/_export_pdf.py                 # DOCUMENTATION.md
    python docs/_export_pdf.py COST            # COST.md
    python docs/_export_pdf.py DOCUMENTATION COST
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

import markdown

docs = Path(__file__).resolve().parent
out_dir = docs / "pdf"
html_dir = docs / "_pdf_tmp"
out_dir.mkdir(exist_ok=True)
html_dir.mkdir(exist_ok=True)

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
DEFAULT_STEMS = ["DOCUMENTATION"]

css = """
@page { size: A4; margin: 14mm; }
body {
  font-family: Tahoma, "Segoe UI", Arial, sans-serif;
  font-size: 10.5pt;
  color: #111827;
  line-height: 1.45;
}
h1 {
  color: #0f766e;
  font-size: 20pt;
  border-bottom: 2px solid #0f766e;
  padding-bottom: 6px;
}
h2 {
  color: #134e4a;
  font-size: 13pt;
  margin-top: 16px;
  border-bottom: 1px solid #99f6e4;
  padding-bottom: 3px;
  page-break-after: avoid;
}
h3 {
  color: #115e59;
  font-size: 11.5pt;
  margin-top: 12px;
  page-break-after: avoid;
}
h4 {
  color: #0f766e;
  font-size: 10.5pt;
  margin-top: 10px;
  page-break-after: avoid;
}
blockquote {
  background: #ecfdf5;
  border-left: 4px solid #0f766e;
  margin: 8px 0;
  padding: 6px 10px;
  color: #134e4a;
}
blockquote strong {
  display: block;
  letter-spacing: 0.03em;
  font-size: 11pt;
}
code {
  background: #f3f4f6;
  padding: 1px 3px;
  border: 1px solid #e5e7eb;
  font-family: Consolas, "Courier New", monospace;
  font-size: 9pt;
}
pre {
  background: #f8fafc;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #0f766e;
  padding: 8px 10px;
  font-size: 8.5pt;
  white-space: pre-wrap;
  font-family: Consolas, "Courier New", monospace;
}
pre code { background: transparent; border: none; padding: 0; }
table {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
  font-size: 9pt;
  page-break-inside: avoid;
}
th {
  background: #0f766e;
  color: white;
  text-align: left;
  padding: 5px 6px;
}
td {
  border: 1px solid #d1d5db;
  padding: 5px 6px;
  vertical-align: top;
}
tr:nth-child(even) td { background: #f8fafc; }
img {
  max-width: 100%;
  height: auto;
  margin: 10px 0 4px 0;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  page-break-inside: avoid;
}
em {
  display: block;
  font-size: 9pt;
  color: #475569;
  margin: 0 0 12px 0;
}
hr { border: none; border-top: 1px solid #99f6e4; margin: 12px 0; }
ul, ol { margin: 4px 0 4px 16px; }
"""


def fix_img_paths(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        src = match.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = (docs / src).resolve()
        return f'src="{path.as_uri()}"'

    return re.sub(r'src="([^"]+)"', repl, html)


def export(stem: str) -> None:
    src = docs / f"{stem}.md"
    if not src.exists():
        raise SystemExit(f"Missing {src}")

    body = markdown.markdown(
        src.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "sane_lists", "toc"],
    )
    body = fix_img_paths(body)
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{css}</style></head><body>{body}</body></html>"
    )
    html_path = html_dir / f"{stem}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = out_dir / f"{stem}.pdf"
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            pass
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=False,
    )
    for _ in range(30):
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            break
        time.sleep(0.25)
    print("OK", pdf_path, pdf_path.stat().st_size if pdf_path.exists() else 0)


def main() -> None:
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    for stem in sys.argv[1:] or DEFAULT_STEMS:
        export(stem.removesuffix(".md"))


if __name__ == "__main__":
    main()
