"""What the source document prints in a block, read BY POSITION (not from joined text).

A Sea bill of lading is a grid of boxes, each with a small heading ('CONSIGNEE', 'NOTIFY PARTY', 'DESCRIPTION OF GOODS' ...). Joined page text
interleaves the left and right boxes, so a value read from it can belong to the wrong party. Here the heading is located with its word
coordinates, the box is the column that starts at the heading, and the value is the text under it down to the next box heading.
Returns '' when the document has no such box (then there is nothing to compare: not a finding) or when the page has no text layer."""
from __future__ import annotations

import io
import logging
import re

log = logging.getLogger(__name__)

# box headings of the party blocks and a few more; a heading must START a cell (nothing but a gap before it on its line)
HEADINGS: dict[str, list[str]] = {
    "shipper": [r"SHIPPER\s*/\s*EXPORTER", r"SHIPPER", r"EXPORTER"],
    "consignee": [r"CONSIGNEE"],
    "notify party": [r"NOTIFY\s+PARTY", r"NOTIFY"],
    "for delivery": [r"FOR\s+DELIVERY", r"DELIVERY\s+AGENT"],
}
# NOT read by position: the goods description (its heading sits in a table header far above its contents) and the small boxes (place of delivery, final
# destination, ports, vessel): a blank box leaks the next table row and a legal clause can look like a heading (tried 14-Nov); a wrong value is worse than none
# any of these, starting a cell below the heading, ends the box above it
STOPPERS = re.compile(r"^(SHIPPER|EXPORTER|CONSIGNEE|NOTIFY|ALSO\s+NOTIFY|FORWARDING|FMC|PRE-?\s?CARRIAGE|PLACE\s+OF|OCEAN\s+VESSEL|VESSEL|PORT\s+OF|"
                      r"FINAL\s+DEST|TYPE\s+OF\s+MOVEMENT|PARTICULARS|EXPORT\s+REFERENCES|BOOKING|B/L\s+NO|SEA\s+WAYBILL\s+NO|FREIGHT\s+&|DECLARED|\*\*|"
                      r"GROSS\s+WEIGHT|MARKS|CNTR|FOR\s+DELIVERY|DELIVERY\s+AGENT|DESCRIPTION|SERVICE\s+CONTRACT)", re.IGNORECASE)
MAX_LINES = {"description": 8}
DEFAULT_MAX_LINES = 9
GAP = 14.0          # a horizontal gap wider than this between two words starts a new cell


def _lines(page) -> list[dict]:
    """Lines of the page as [{top, bottom, words:[{text,x0,x1}]}], words in reading order."""
    words = page.extract_words(keep_blank_chars=False, use_text_flow=False, x_tolerance=1.5, y_tolerance=2)
    words.sort(key=lambda w: (round(w["top"]), w["x0"]))
    lines: list[dict] = []
    for w in words:
        if lines and abs(w["top"] - lines[-1]["top"]) <= 2.5:
            lines[-1]["words"].append(w)
            lines[-1]["bottom"] = max(lines[-1]["bottom"], w["bottom"])
        else:
            lines.append({"top": w["top"], "bottom": w["bottom"], "words": [w]})
    for ln in lines:
        ln["words"].sort(key=lambda w: w["x0"])
    return lines


def _cells(line: dict) -> list[list[dict]]:
    """A line split into cells at wide horizontal gaps."""
    cells: list[list[dict]] = []
    for w in line["words"]:
        if cells and w["x0"] - cells[-1][-1]["x1"] <= GAP:
            cells[-1].append(w)
        else:
            cells.append([w])
    return cells


def _text(words: list[dict]) -> str:
    return " ".join(w["text"] for w in words)


def block_on_page(page, key: str) -> str:
    """The text of the box whose heading is `key` ('consignee', 'notify party' ...) on this page, '' when the page has no such box."""
    pats = [re.compile(r"^" + p + r"\b", re.IGNORECASE) for p in HEADINGS[key]]
    lines = _lines(page)
    width = float(page.width)
    limit = MAX_LINES.get(key, DEFAULT_MAX_LINES)
    for li, ln in enumerate(lines):
        for cell in _cells(ln):
            head = _text(cell)
            if not any(p.match(head) for p in pats):
                continue
            idx = ln["words"].index(cell[0])
            x0 = cell[0]["x0"] - 3
            nxt = [c for c in _cells(ln) if c[0]["x0"] > cell[0]["x0"]]
            x1 = (nxt[0][0]["x0"] - 2) if nxt else width
            # the heading cell may carry the first value words after the heading text (e.g. 'NOTIFY PARTY (It is agreed ...)'): skip them
            rows: list[str] = []
            for nl in lines[li + 1: li + 1 + 40]:
                col = [w for w in nl["words"] if w["x0"] >= x0 and w["x1"] <= x1 + 2]
                if not col:
                    continue
                first_cell = _cells({"words": col})[0]
                if STOPPERS.match(_text(first_cell)) and nl["top"] - ln["bottom"] > 4:
                    break
                rows.append(_text(col))
                if len(rows) >= limit:
                    break
            return " ".join(rows).strip()
    return ""


def _plausible(text: str) -> bool:
    """A box value is a few words of letters, not a stray line of numbers or a long run of clauses."""
    return 3 <= len(text) <= 260 and len(re.findall(r"[A-Za-z]{3,}", text)) >= 1


def blocks_from_pdf(pdf_bytes: bytes, pages_1based: list[int], keys: list[str] | None = None) -> dict[str, tuple[str, int]]:
    """{key: (text, page)} for the boxes found on the given pages (the first page that has the box wins). Never raises."""
    import pdfplumber
    keys = keys or list(HEADINGS)
    out: dict[str, tuple[str, int]] = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for no in pages_1based:
                if no - 1 >= len(pdf.pages):
                    continue
                for k in keys:
                    if k in out:
                        continue
                    t = block_on_page(pdf.pages[no - 1], k)
                    if t and _plausible(t):
                        out[k] = (t, no)
    except Exception as exc:                                           # a document problem must never stop a check
        log.warning("could not read the boxes of the document by position: %s", exc)
    return out
