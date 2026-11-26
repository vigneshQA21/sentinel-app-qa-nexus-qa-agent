"""Sample file label vs the document's printed title (26 Nov 2026: three Japan files labelled 'DEBIT NOTE' print INVOICE).

A sample file is named '<nn> <TYPE> - <name>.pdf'; the test case expects that TYPE in Nexus. If the document's own title says another
type, the expectation is wrong, not Nexus: list it before any run so a mislabelled file never becomes a false bug."""
from __future__ import annotations

import re
from pathlib import Path

from .debit_rule import is_agent_bill

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


def check_file(name: str, head: str, billed_to: list[str] | tuple[str, ...] = (), starts: list[str] | tuple[str, ...] = ()) -> str:
    """'' when fine; else why the label and the printed title disagree. An INVOICE billed to one of `billed_to` (LOGISTEED EXPRESS)
    is the agent's Debit Note (debit_rule.py), so a DEBIT NOTE label on it is right, and an INVOICE label is the wrong one."""
    m = LABEL.match(name)
    if not m or m.group(1).strip() not in TITLES:
        return ""
    label = m.group(1).strip()
    if is_agent_bill(head, billed_to, starts):
        return "" if label == "DEBIT NOTE" else f"labelled {label} but it is an invoice with {(list(billed_to) + list(starts))[0]} on it: a DEBIT NOTE"
    found = title_types(head)
    if not found or label in found:
        return ""
    return f"labelled {label} but the document's title says {found[0]}"


def scan(samples_dir: Path, billed_to: list[str] | tuple[str, ...] = (), starts: list[str] | tuple[str, ...] = (), head_lines: int = 60) -> list[tuple[str, str]]:
    """[(file, problem)] for every labelled sample PDF whose printed title contradicts its label (text PDFs only)."""
    from .pdf_split import page_texts_layout
    out = []
    for f in sorted(samples_dir.glob("*/*.pdf")):
        try:
            first = page_texts_layout(f.read_bytes(), ocr=False)[0]
        except Exception:
            continue
        head = "\n".join([l for l in first.splitlines() if l.strip()][:head_lines])
        why = check_file(f.name, head, billed_to, starts)
        if why:
            out.append((f"{f.parent.name}/{f.name}", why))
    return out
