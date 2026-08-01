"""Convert docs/*.md to PDF via Chrome headless (best Arabic + layout)."""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import markdown

docs = Path(__file__).resolve().parent
out_dir = docs / "pdf"
html_dir = docs / "_pdf_tmp"
out_dir.mkdir(exist_ok=True)
html_dir.mkdir(exist_ok=True)

CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

files = [
    "ARCHITECTURE.md",
    "FLOWS.md",
    "DEPLOY.md",
    "KNOWN_ISSUES.md",
]

css = """
@page { size: A4; margin: 16mm; }
body {
  font-family: Tahoma, "Segoe UI", Arial, sans-serif;
  font-size: 11pt;
  color: #111827;
  line-height: 1.5;
  max-width: 180mm;
}
h1 {
  color: #0f766e;
  font-size: 22pt;
  border-bottom: 2px solid #0f766e;
  padding-bottom: 6px;
}
h2 {
  color: #134e4a;
  font-size: 14pt;
  margin-top: 18px;
  border-bottom: 1px solid #99f6e4;
  padding-bottom: 4px;
}
h3 {
  color: #115e59;
  font-size: 12pt;
  margin-top: 14px;
}
blockquote {
  background: #ecfdf5;
  border-left: 4px solid #0f766e;
  margin: 10px 0;
  padding: 8px 12px;
  color: #134e4a;
}
code {
  background: #f3f4f6;
  color: #111827;
  padding: 1px 4px;
  border: 1px solid #e5e7eb;
  font-family: Consolas, "Courier New", monospace;
  font-size: 9.5pt;
}
pre {
  background: #f8fafc;
  color: #111827;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #0f766e;
  padding: 10px 12px;
  font-size: 9pt;
  white-space: pre-wrap;
  font-family: Consolas, "Courier New", monospace;
}
pre code {
  background: transparent;
  border: none;
  padding: 0;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 10px 0;
  font-size: 10pt;
}
th {
  background: #0f766e;
  color: white;
  text-align: left;
  padding: 7px 8px;
}
td {
  border: 1px solid #d1d5db;
  padding: 7px 8px;
  vertical-align: top;
}
tr:nth-child(even) td { background: #f8fafc; }
img { max-width: 100%; height: auto; margin: 10px 0; }
hr { border: none; border-top: 1px solid #99f6e4; margin: 16px 0; }
ul, ol { margin: 6px 0 6px 18px; }
"""


def fix_img_paths(html: str) -> str:
    def repl(match: re.Match[str]) -> str:
        src = match.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return match.group(0)
        path = (docs / src).resolve()
        return f'src="{path.as_uri()}"'

    return re.sub(r'src="([^"]+)"', repl, html)


def open_target(name: str) -> Path:
    target = out_dir / name
    try:
        with open(target, "wb"):
            pass
        return target
    except PermissionError:
        alt = docs / "pdf_readable" / name
        alt.parent.mkdir(exist_ok=True)
        return alt


def md_to_pdf(md_name: str) -> Path:
    md_path = docs / md_name
    text = md_path.read_text(encoding="utf-8")
    body = markdown.markdown(
        text, extensions=["tables", "fenced_code", "sane_lists"]
    )
    body = fix_img_paths(body)
    html = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<style>{css}</style></head><body>{body}</body></html>"
    )
    html_path = html_dir / f"{md_path.stem}.html"
    html_path.write_text(html, encoding="utf-8")
    pdf_path = open_target(f"{md_path.stem}.pdf")
    if pdf_path.exists():
        try:
            pdf_path.unlink()
        except OSError:
            pass
    cmd = [
        str(CHROME),
        "--headless=new",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.resolve().as_uri(),
    ]
    subprocess.run(cmd, check=False)
    # Chrome may finish writing slightly after process exit
    for _ in range(20):
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            break
        time.sleep(0.25)
    return pdf_path


def main() -> None:
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found: {CHROME}")
    ok_all = True
    for name in files:
        try:
            pdf_path = md_to_pdf(name)
            size = pdf_path.stat().st_size if pdf_path.exists() else 0
            if size < 1000:
                print("FAIL", name, "empty/missing pdf")
                ok_all = False
            else:
                print("OK", pdf_path, size)
        except Exception as exc:  # noqa: BLE001
            print("FAIL", name, type(exc).__name__)
            ok_all = False
    print("done" if ok_all else "errors")


if __name__ == "__main__":
    main()
