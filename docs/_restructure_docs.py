"""Restructure DOCUMENTATION.md: product → architecture → ops → reference."""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parent / "DOCUMENTATION.md"
text = SRC.read_text(encoding="utf-8")

parts = re.split(r"(?=^## \d+\. )", text, flags=re.M)
sections: dict[str, str] = {}
for part in parts[1:]:
    m = re.match(r"^## (\d+)\. ([^\n]+)", part)
    if not m:
        continue
    title = m.group(2).strip()
    sections[title] = part

needed = [
    "Project Overview",
    "Version Control & Timeline",
    "Requirements & Roles",
    "Technology Stack",
    "System Architecture",
    "Code Architecture",
    "Source Layout",
    "Configuration Architecture",
    "Data Flow Architecture",
    "Startup, Webhook & API",
    "Conversation Engine",
    "Conversation Flows",
    "Booking Architecture",
    "Reschedule, Cancel, Hours & Holidays",
    "Reminders",
    "Voice Architecture",
    "System Prompts",
    "Safety & Handover",
    "Database Design",
    "Admin Dashboard",
    "DevOps & Deployment",
    "User Manual",
    "GUI Screenshots",
    "Testing",
    "Document History",
    "Appendix",
]
missing = [t for t in needed if t not in sections]
if missing:
    raise SystemExit(f"Missing sections: {missing}\nHave: {list(sections)}")

FIG_LABELS = {
    "fig01-system-context.png": "Figure 1",
    "fig02-layered-architecture.png": "Figure 2",
    "fig03-webhook-routing.png": "Figure 3",
    "fig04-booking-flow.png": "Figure 4",
    "fig05-voice-pipeline.png": "Figure 5",
    "fig06-hold-confirm.png": "Figure 6",
    "fig07-data-model.png": "Figure 7",
    "fig08-deploy-pipeline.png": "Figure 8",
    "fig09-conversation-states.png": "Figure 9",
    "fig10-reminders-handover.png": "Figure 10",
    "fig11-config-architecture.png": "Figure 11",
    "fig12-admin-dashboard.png": "Figure 12",
}


def apply_dedupe(full: str) -> str:
    seen: set[str] = set()

    def repl(m: re.Match[str]) -> str:
        fname = m.group(2)
        if fname not in seen:
            seen.add(fname)
            return m.group(0)
        label = FIG_LABELS.get(fname, fname)
        return f"> See **{label}** earlier in this document.\n\n"

    pattern = (
        r"!\[([^\]]*)\]\(images/(fig\d{2}-[^)]+\.png)\)\n+"
        r"(?:\*[^\n]+\*\n+)?"
    )
    return re.sub(pattern, repl, full)


def strip_mermaid_after_png(section: str) -> str:
    return re.sub(
        r"(!\[[^\]]*\]\(images/fig[^)]+\)\n+(?:\*[^\n]+\*\n+))"
        r"(?:```mermaid[\s\S]*?```\n+)",
        r"\1",
        section,
        count=5,
    )


def renumber(title: str, num: int, body: str) -> str:
    body = re.sub(r"^## \d+\. [^\n]+", f"## {num}. {title}", body, count=1, flags=re.M)

    def subsec(m: re.Match[str]) -> str:
        return f"### {num}.{m.group(1)} {m.group(2)}"

    body = re.sub(r"^### \d+\.(\d+)\s+(.*)$", subsec, body, flags=re.M)
    return body


def split_gui_ops(gui_body: str) -> tuple[str, str]:
    m = re.search(r"### \d+\.\d+\s+Ops screenshots.*", gui_body, flags=re.S)
    if not m:
        return gui_body, ""
    ops = m.group(0)
    main = gui_body[: m.start()].rstrip() + "\n\n"
    ops = re.sub(
        r"^### \d+\.\d+\s+Ops screenshots[^\n]*",
        "### Ops screenshots",
        ops,
        count=1,
        flags=re.M,
    )
    return main, ops


gui_main, ops_block = split_gui_ops(sections["GUI Screenshots"])
devops = sections["DevOps & Deployment"]
if ops_block and "ops-gha-deploy-fail" not in devops:
    devops = devops.rstrip() + "\n\n" + ops_block + "\n"

# Trim duplicate confirmed map in GUI (keep G8, drop G9 if both present)
gui_main = re.sub(
    r"!\[G9[^\]]*\]\([^\)]+\)\n+\*[^\n]+\*\n+",
    "",
    gui_main,
    count=1,
)
# Prefer one cancel confirm detail image if both G16/G17 heavy — keep both for journey clarity

order: list[tuple[str, str]] = [
    ("Project Overview", sections["Project Overview"]),
    ("Requirements & Roles", sections["Requirements & Roles"]),
    ("Technology Stack", sections["Technology Stack"]),
    ("User Manual", sections["User Manual"]),
    ("GUI Screenshots", gui_main),
    ("System Architecture", strip_mermaid_after_png(sections["System Architecture"])),
    ("Code Architecture", strip_mermaid_after_png(sections["Code Architecture"])),
    ("Source Layout", sections["Source Layout"]),
    ("Data Flow Architecture", strip_mermaid_after_png(sections["Data Flow Architecture"])),
    ("Conversation Engine", strip_mermaid_after_png(sections["Conversation Engine"])),
    ("Conversation Flows", strip_mermaid_after_png(sections["Conversation Flows"])),
    ("Booking Architecture", strip_mermaid_after_png(sections["Booking Architecture"])),
    ("Reschedule, Cancel, Hours & Holidays", sections["Reschedule, Cancel, Hours & Holidays"]),
    ("Reminders", sections["Reminders"]),
    ("Voice Architecture", strip_mermaid_after_png(sections["Voice Architecture"])),
    ("Safety & Handover", strip_mermaid_after_png(sections["Safety & Handover"])),
    ("Database Design", strip_mermaid_after_png(sections["Database Design"])),
    ("Admin Dashboard", strip_mermaid_after_png(sections["Admin Dashboard"])),
    ("Configuration Architecture", strip_mermaid_after_png(sections["Configuration Architecture"])),
    ("Startup, Webhook & API", strip_mermaid_after_png(sections["Startup, Webhook & API"])),
    ("DevOps & Deployment", strip_mermaid_after_png(devops)),
    ("Testing", sections["Testing"]),
    ("System Prompts", sections["System Prompts"]),
    ("Version Control & Timeline", sections["Version Control & Timeline"]),
    ("Document History", sections["Document History"]),
    ("Appendix", sections["Appendix"]),
]

renumbered: list[str] = []
for i, (title, body) in enumerate(order, start=1):
    renumbered.append(renumber(title, i, body).rstrip() + "\n")

toc_lines = [
    "# Hospital Chatbot — Technical & Architecture Documentation",
    "",
    "| | |",
    "|:--|:--|",
    "| **Version** | 4.0 |",
    "| **Updated** | 2026-08-06 |",
    "| **Repository** | [Ghena-A/hospital-chatbot](https://github.com/Ghena-A/hospital-chatbot) |",
    "| **API** | FastAPI `1.0.0` — `uvicorn app.main:app` |",
    "| **Related** | [`README.md`](../README.md) · [`DEPLOYMENT.md`](DEPLOYMENT.md) · `docs/pdf/DOCUMENTATION.pdf` |",
    "| **Figures** | Architecture: `docs/images/fig01`–`fig12` · GUI: `docs/images/gui/` |",
    "",
    "> **How to read this guide**  ",
    "> **Product / stakeholders:** §§1–5 (overview, requirements, user manual, GUI).  ",
    "> **Engineering:** §§6–20 (architecture, flows, booking, voice, DB, config, API).  ",
    "> **Ops:** §§21–22 (deploy, testing).  ",
    "> **Reference:** §§23–26 (prompts, git timeline, history, appendix).",
    "",
    "---",
    "",
    "## Table of contents",
    "",
]
for i, (title, _) in enumerate(order, start=1):
    anchor = re.sub(r"[^\w\s-]", "", title.lower())
    anchor = re.sub(r"\s+", "-", anchor.strip())
    toc_lines.append(f"{i}. [{title}](#{i}-{anchor})")

toc_lines += [
    "",
    "### List of figures",
    "",
    "| Fig | Title | File |",
    "|:---:|:------|:-----|",
    "| 1 | System context | `images/fig01-system-context.png` |",
    "| 2 | Layered code architecture | `images/fig02-layered-architecture.png` |",
    "| 3 | Webhook message routing | `images/fig03-webhook-routing.png` |",
    "| 4 | Booking flow | `images/fig04-booking-flow.png` |",
    "| 5 | Voice pipeline | `images/fig05-voice-pipeline.png` |",
    "| 6 | Slot hold & confirm | `images/fig06-hold-confirm.png` |",
    "| 7 | Core data model | `images/fig07-data-model.png` |",
    "| 8 | Deploy pipeline | `images/fig08-deploy-pipeline.png` |",
    "| 9 | Conversation states | `images/fig09-conversation-states.png` |",
    "| 10 | Reminders & handover | `images/fig10-reminders-handover.png` |",
    "| 11 | Configuration architecture | `images/fig11-config-architecture.png` |",
    "| 12 | Admin dashboard map | `images/fig12-admin-dashboard.png` |",
    "| G1–G31 | Live GUI (WhatsApp + Streamlit) | `images/gui/` (§5) |",
    "| G32–G33 | Ops (Actions / server) | under §21 DevOps |",
    "",
    "---",
    "",
]

# Append history row for 4.0
hist_idx = next(i for i, (t, _) in enumerate(order) if t == "Document History")
hist = renumbered[hist_idx]
if "| **4.0** |" not in hist and "| 4.0 |" not in hist:
    hist = hist.rstrip() + (
        "\n| **2026-08-06** | **4.0** | **Restructured: product→architecture→ops→reference; "
        "GUI after User Manual; timeline moved late; figure dedupe; ops shots under DevOps** |\n\n"
    )
    renumbered[hist_idx] = hist

full = "\n".join(toc_lines) + "\n".join(renumbered)
full = apply_dedupe(full)
full = re.sub(r"\n\*G(\d+)\. ", r"\n*Figure G\1. ", full)

full = re.sub(
    r"\*End of guide[^\n]*",
    "*End of guide — Hospital Chatbot Technical & Architecture Documentation v4.0*",
    full,
)
if "*End of guide" not in full:
    full = full.rstrip() + (
        "\n\n*End of guide — Hospital Chatbot Technical & Architecture Documentation v4.0*\n"
    )

SRC.write_text(full, encoding="utf-8")
print("Wrote", SRC, "lines", full.count("\n") + 1)
embeds = re.findall(r"images/(fig\d{2}-[^)]+\.png)", full)
c = Counter(embeds)
dups = {k: v for k, v in c.items() if v > 1}
print("Figure embed counts:", dict(c))
print("Duplicates remaining:", dups or "none")
print("First headings:")
for line in full.splitlines():
    if re.match(r"^## \d+\. ", line):
        print(" ", line)
