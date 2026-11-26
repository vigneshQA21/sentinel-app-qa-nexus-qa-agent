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


# Small boxes of a bill (one value under a heading in a grid row). Read only the line directly under the heading, inside the heading's own
# column, and only if it looks like a value of that kind; a blank box gives '' (never the next table row's text).
SMALL_BOXES: dict[str, tuple[list[str], str]] = {
    "vessel": ([r"OCEAN\s+VESSEL", r"VESSEL(?:\s+NAME)?", r"VESSEL\s*/\s*VOYAGE"], r"[A-Za-z]{3,}"),
    "voyage": ([r"VOY(?:AGE)?\.?\s*(?:NO\.?)?"], r"\w{2,}"),
    "port of loading": ([r"PORT\s+OF\s+LOADING"], r"[A-Za-z]{3,}"),
    "port of discharge": ([r"PORT\s+OF\s+DISCHARGE"], r"[A-Za-z]{3,}"),
    "place of receipt": ([r"PLACE\s+OF\s+RECEIPT"], r"[A-Za-z]{3,}"),
    "place of delivery": ([r"PLACE\s+OF\s+DELIVERY"], r"[A-Za-z]{3,}"),
    "final destination": ([r"FINAL\s+DESTINATION"], r"[A-Za-z]{3,}"),
    "place of issue": ([r"PLACE\s+(?:AND\s+DATE\s+)?OF\s+(?:BILL\(S\)\s+)?ISSUE"], r"[A-Za-z]{3,}"),
    "date of issue": ([r"DATE\s+OF\s+ISSUE", r"ISSUE\s+DATE"], r"\d"),
    "on board date": ([r"(?:SHIPPED\s+)?ON\s+BOARD\s+DATE", r"LADEN\s+ON\s+BOARD"], r"\d"),
    "booking": ([r"BOOKING\s*(?:NO\.?|NUMBER)"], r"\d{4,}|[A-Z]{2,}\d{3,}"),
    "bill no": ([r"B/L\s*(?:NO\.?|NUMBER)", r"BILL\s+OF\s+LADING\s*(?:NO\.?|NUMBER)", r"(?:SEA\s+)?WAYBILL\s*(?:NO\.?|NUMBER)"], r"[A-Z0-9]{6,}"),
    "type of movement": ([r"TYPE\s+OF\s+MOVEMENT", r"MOVE\s+TYPE", r"SERVICE\s+TYPE"], r"[A-Za-z]{2,}"),
}


HEADING_ONLY = re.compile(r"^(?:(?:VOYAGE|VOY|NO\.?|FLAG|PORT|OF|PLACE|DELIVERY|DISCHARGE|LOADING|RECEIPT|VESSEL|NAME|TYPE|MOVEMENT|"
                          r"FINAL|DESTINATION|DATE|ISSUE|BOOKING|NUMBER|B/L|AND|PRE-?CARRIAGE|BY)\W*)+$", re.IGNORECASE)


def _box_value_ok(val: str, looks: str) -> bool:
    """A box value: matches its kind, is not another heading, and is not a sentence of the bill's printed terms (mostly lower case)."""
    if not val or STOPPERS.match(val) or HEADING_ONLY.match(val) or not re.search(looks, val) or val.lstrip().startswith("("):
        return False
    if len(re.findall(r"PORT\s+OF|PLACE\s+OF|FINAL\s+DEST|\bVESSEL\b|\bVOYAGE\b|\bFLAG\b|TYPE\s+OF\s+MOVEMENT|DESCRIPTION\s+OF", val, re.IGNORECASE)) >= 2:
        return False                                                     # a row of other headings, not a value
    words = re.findall(r"[A-Za-z]{2,}", val)
    lower = [w for w in words if w.islower()]
    return not (len(lower) >= 3 and len(lower) >= len(words) / 2)


def small_box_on_page(page, key: str) -> str:
    pats, looks = SMALL_BOXES[key]
    rx = [re.compile(r"(?<![A-Za-z])" + p + r"(?![A-Za-z])", re.IGNORECASE) for p in pats]
    lines = _lines(page)
    width = float(page.width)
    for li, ln in enumerate(lines):
        cells = _cells(ln)
        for ci, cell in enumerate(cells):
            head = _text(cell)
            m = next((r.match(head) for r in rx if r.match(head)), None)  # a box heading STARTS its cell; never a phrase inside a clause
            if not m or not m.group(0).isupper():                       # headings are printed in capitals; title-case words are the bill's terms
                continue
            rest = head[m.end():].strip(" :：.-/")
            if rest and _box_value_ok(rest, looks):
                return rest[:100]                                        # 'PORT OF LOADING: SHANGHAI' on one line
            x0 = cell[0]["x0"] - 3
            x1 = (cells[ci + 1][0]["x0"] - 2) if ci + 1 < len(cells) else width
            height = max(ln["bottom"] - ln["top"], 6.0)
            for nl in lines[li + 1: li + 3]:
                if nl["top"] - ln["bottom"] > 2.6 * height:               # too far below: this box is blank, look for another heading
                    break
                col = [w for w in nl["words"] if w["x0"] >= x0 and w["x1"] <= x1 + 2]
                if not col:
                    continue
                val = _text(col).strip()
                if _box_value_ok(val, looks):
                    return val[:100]
                break                                                     # not a value: keep looking for another heading
    return ""


def small_boxes_from_pdf(pdf_bytes: bytes, pages_1based: list[int], keys: list[str]) -> dict[str, tuple[str, int]]:
    """{key: (value, page)} for the small boxes found on the given pages. Never raises."""
    import pdfplumber
    out: dict[str, tuple[str, int]] = {}
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for no in pages_1based:
                if no - 1 >= len(pdf.pages):
                    continue
                for k in keys:
                    if k not in out:
                        v = small_box_on_page(pdf.pages[no - 1], k)
                        if v:
                            out[k] = (v, no)
    except Exception as exc:
        log.warning("could not read the small boxes of the document by position: %s", exc)
    return out
