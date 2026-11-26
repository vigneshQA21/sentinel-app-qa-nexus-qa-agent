"""Sample file label vs the document's printed title (26 Nov 2026: three Japan files labelled 'DEBIT NOTE' print INVOICE).

A sample file is named '<nn> <TYPE> - <name>.pdf'; the test case expects that TYPE in Nexus. If the document's own title says another
type, the expectation is wrong, not Nexus: list it before any run so a mislabelled file never becomes a false bug."""
from __future__ import annotations

import re
from pathlib import Path

# type label -> the title words that confirm it, and titles of other types that contradict it
TITLES = {
    "DEBIT NOTE": r"\bDEBIT\s+NOTE\b",
    "CREDIT NOTE": r"\bCREDIT\s+NOTE\b",
    "INVOICE": r"\b(?:COMMERCIAL\s+|TAX\s+)?INVOICE\b",
    "PACKING LIST": r"\bPACKING\s+LIST\b",
    "MANIFEST": r"\bMANIFEST\b",
    "BOOKING CONFIRMATION": r"\bBOOKING\b",
}
LABEL = re.compile(r"^\d+\s+([A-Z][A-Z ]+?)\s+-\s+")


def title_types(head: str) -> list[str]:
    """Types whose title appears in the first lines of the document, in the order they appear."""
    hits = [(m.start(), t) for t, rx in TITLES.items() for m in [re.search(rx, head, re.IGNORECASE)] if m]
    return [t for _, t in sorted(hits)]


def check_file(name: str, head: str) -> str:
    """'' when fine; else why the label and the printed title disagree."""
    m = LABEL.match(name)
    if not m or m.group(1).strip() not in TITLES:
        return ""
    label = m.group(1).strip()
    found = title_types(head)
    if not found or label in found:
        return ""
    return f"labelled {label} but the document's title says {found[0]}"


def scan(samples_dir: Path, head_chars: int = 400) -> list[tuple[str, str]]:
    """[(file, problem)] for every labelled sample PDF whose printed title contradicts its label (text PDFs only)."""
    import pdfplumber
    out = []
    for f in sorted(samples_dir.glob("*/*.pdf")):
        try:
            with pdfplumber.open(f) as pdf:
                head = (pdf.pages[0].extract_text() or "")[:head_chars]
        except Exception:
            continue
        why = check_file(f.name, head)
        if why:
            out.append((f"{f.parent.name}/{f.name}", why))
    return out
