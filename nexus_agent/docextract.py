"""What the document prints for one field, as a value (rule, 26 Nov 2026: "Document says" is never blank).

Order of evidence for a field:
  1. a labelled value: the text after the field's label on the document (VESSEL / PORT OF LOADING / PLACE AND DATE OF ISSUE / ...),
     or a value of a recognisable form (container number, container type, weight in KGS, volume in CBM, FREIGHT PREPAID/COLLECT, Incoterm);
  2. the document line that best matches the value Nexus shows (said so: "matching line");
  3. NO_VALUE ("no value found in the document").
Each result says where it was read (label / form / line), so the report can show the document value next to the Nexus value."""
from __future__ import annotations

import re

NO_VALUE = "no value found in the document"

INCOTERMS = r"(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)"

# Nexus field label (lower case, regex) -> document labels that introduce its value (regex, upper case text)
LABELS: list[tuple[str, list[str]]] = [
    (r"^vessel( name)?$", [r"VESSEL(?:\s*NAME)?", r"OCEAN VESSEL", r"M/?V"]),
    (r"^voyage( no\.?)?$", [r"VOY(?:AGE)?\.?\s*(?:NO\.?)?"]),
    (r"^port of loading$|^ctn pol city$|^from$", [r"PORT OF LOADING", r"POL\b", r"LOADING PORT"]),
    (r"^port of discharge$|^ctn pod city$|^to$", [r"PORT OF DISCHARGE", r"POD\b", r"DISCHARGE PORT"]),
    (r"^place of receipt$", [r"PLACE OF RECEIPT"]),
    (r"^place of delivery$|^final destination$", [r"PLACE OF DELIVERY", r"FINAL DESTINATION"]),
    (r"^place$|^place of issue$", [r"PLACE (?:AND DATE )?OF (?:BILL\(S\) )?ISSUE", r"PLACE OF ISSUE"]),
    (r"^date$|^date of issue$|^issue date$", [r"DATE OF ISSUE", r"PLACE AND DATE OF ISSUE", r"ISSUE DATE"]),
    (r"^shipped on board date$|^on board date$", [r"(?:SHIPPED )?ON BOARD DATE", r"LADEN ON BOARD"]),
    (r"^bill no\.?$|^b/?l no\.?$|^air waybill number$|^house number", [r"B/L\s*(?:NO\.?|NUMBER)", r"BILL OF LADING\s*(?:NO\.?|NUMBER)",
                                                                         r"WAYBILL\s*(?:NO\.?|NUMBER)", r"SEA WAYBILL NO\.?"]),
    (r"^booking( no\.?)?$", [r"BOOKING\s*(?:NO\.?|NUMBER)"]),
    (r"^carrier name$|^carrier$", [r"CARRIER", r"SHIPPING LINE"]),
    (r"^description$|^nature and quantity of goods$", [r"DESCRIPTION OF (?:PACKAGES AND )?GOODS", r"DESCRIPTION"]),
    (r"^inv(?:oice)? no\.?$", [r"INV(?:OICE)?\.?\s*(?:NO\.?|NUMBER)"]),
    (r"^seal( no\.?)?$", [r"SEAL\s*(?:NO\.?)?"]),
    (r"^move type$", [r"MOVE TYPE", r"SERVICE TYPE", r"TERM"]),
    (r"^load term$", [r"LOAD TERM"]),
]

# value forms that identify a field without a label
FORMS: list[tuple[str, str]] = [
    (r"^container( no\.?| number)?$", r"\b([A-Z]{4}\s?\d{7})\b"),
    (r"^container type$", r"\b((?:20|40|45)\s?'?\s?(?:DRY|GP|DC|HC|HQ|RF|RH|OT|FR|STD|HIGH CUBE)\b(?:\s?\d'\d)?)"),
    (r"^freight( payment)?$|^freight terms$", r"\b(FREIGHT\s+(?:PREPAID|COLLECT)|PREPAID|COLLECT)\b"),
    (r"^incoterm$", r"\b" + INCOTERMS + r"\b"),
    (r"^gross weight( value)?$|^weight$", r"(\d[\d,]*(?:\.\d+)?\s*(?:KGS?|KILOS?)\b)"),
    (r"^volume( of goods)?( value)?$|^measurement$", r"(\d[\d,]*(?:\.\d+)?\s*(?:CBM|M3|MTQ)\b)"),
    (r"^no of pieces value$|^pieces$|^no\.? of packages$", r"(\d[\d,]*\s*(?:PKGS?|PACKAGES?|CTNS?|CARTONS?|PLTS?|PALLETS?|PCS|PIECES|CASES?|BUNDLES?)\b)"),
]


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _after_label(lines: list[str], pattern: str) -> str:
    """Text after the label on its line; the next line when the label stands alone (a box heading)."""
    rx = re.compile(r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])\s*[:：/.\-]?\s*", re.IGNORECASE)   # whole words: SHIPPING LINE is not inside LINES
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if not m:
            continue
        rest = ln[m.end():].strip(" :：-")
        if len(rest) >= 2 and not re.fullmatch(r"[\W_]+", rest):
            return rest[:100]
        if i + 1 < len(lines):
            return lines[i + 1][:100]
    return ""


def _human(pattern: str) -> str:
    """A regex label written as plain words for the report: 'DESCRIPTION OF (?:PACKAGES AND )?GOODS' -> 'DESCRIPTION OF GOODS'."""
    t = re.sub(r"\(\?:[^)]*\)\??", "", pattern)
    t = re.sub(r"\\s\*|\\s\+|\\s", " ", t)
    t = re.sub(r"[\\?()\[\]|*+^$]|\\b|\\.", "", t)
    return " ".join(t.split())


HEADING_WORDS = {"PORT", "OF", "PLACE", "DELIVERY", "DISCHARGE", "LOADING", "RECEIPT", "TYPE", "MOVEMENT", "DESCRIPTION", "GOODS", "PACKAGES",
                 "FIELD", "IF", "MIXED", "USE", "AND", "NO", "NUMBER", "VESSEL", "VOYAGE", "FINAL", "DESTINATION", "MARKS", "WEIGHT", "GROSS",
                 "MEASUREMENT", "FREIGHT", "CHARGES", "CONTAINER", "SEAL", "DATE", "ISSUE", "BOOKING"}


def _plain_value(v: str) -> bool:
    """Not a sentence of the bill's printed terms (mostly lower-case words) and not only headings."""
    from .docvalue import _box_value_ok
    return _box_value_ok(v, r"\w{2,}")


def _looks_like_heading(v: str) -> bool:
    """Text after a label that is really more heading (other labels, a dangling ')'), not a value."""
    words = re.findall(r"[A-Za-z]+", v.upper())
    unbalanced = v.count(")") > v.count("(")
    return unbalanced or (bool(words) and sum(w in HEADING_WORDS for w in words) / len(words) >= 0.6)


# Nexus field label (lower case) -> small box of the bill read by position (docvalue.SMALL_BOXES)
BOX_FOR = [(r"^vessel( name)?$", "vessel"), (r"^voyage( no\.?)?$", "voyage"), (r"^port of loading$|^ctn pol city$", "port of loading"),
           (r"^port of discharge$|^ctn pod city$", "port of discharge"), (r"^place of receipt$", "place of receipt"),
           (r"^place of delivery$", "place of delivery"), (r"^final destination$", "final destination"), (r"^place$|^place of issue$", "place of issue"),
           (r"^date$|^date of issue$|^issue date$", "date of issue"), (r"^shipped on board date$|^on board date$", "on board date"),
           (r"^booking( no\.?)?$", "booking"), (r"^bill no\.?$|^b/?l no\.?$|^air waybill number$", "bill no"), (r"^move type$", "type of movement")]


def extract_from_source(src: dict, label: str, value: str) -> tuple[str, str]:
    """Most precise first: the bill's small box read by position (text PDFs), then extract() on the bill's text. (value, how)."""
    lab = (label or "").strip().lower()
    key = next((k for rx, k in BOX_FOR if re.search(rx, lab)), None)
    if key and src.get("pdf") and not src.get("scanned"):
        if "small_boxes" not in src:
            from .docvalue import SMALL_BOXES, small_boxes_from_pdf
            try:
                src["small_boxes"] = small_boxes_from_pdf(src["pdf"].read_bytes(), src.get("pages", []), list(SMALL_BOXES))
            except Exception:
                src["small_boxes"] = {}
        if key in src["small_boxes"]:
            v, pg = src["small_boxes"][key]
            return v, f"by position from the box '{key.upper()}' on page {pg}"
    return extract(label, value, src.get("text", ""))


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[A-Z0-9]+", (s or "").upper()) if len(t) > 1}


def matching_line(text: str, value: str) -> str:
    """The document line sharing most words with the Nexus value (at least half of them), else ''."""
    want = _tokens(value)
    if not want:
        return ""
    best, score = "", 0.0
    for ln in _lines(text):
        s = len(want & _tokens(ln)) / len(want)
        if s > score:
            best, score = ln, s
    return best[:120] if score >= 0.5 else ""


def extract(label: str, value: str, text: str) -> tuple[str, str]:
    """(document value, how it was found) for one field; (NO_VALUE, '') when the document has nothing for it."""
    lab = (label or "").strip().lower()
    lines = _lines(text)
    upper = "\n".join(lines).upper()
    for lab_rx, doc_labels in LABELS:
        if re.search(lab_rx, lab):
            for dl in doc_labels:
                v = _after_label(lines, dl)
                if v and not _looks_like_heading(v) and _plain_value(v):
                    return v, f"after the label '{_human(dl)}'"
    for lab_rx, form in FORMS:
        if re.search(lab_rx, lab):
            found = list(dict.fromkeys(m.group(1).strip() for m in re.finditer(form, upper)))
            if found:
                return ", ".join(found[:4]), "value of this form printed on the document"
    if value:
        ln = matching_line(text, value)
        if ln:
            return ln, "matching line on the document"
    return NO_VALUE, ""


def fill_blanks(rows: list[dict]) -> list[dict]:
    """Safety net before any report is written: a blank 'Document says' becomes NO_VALUE (never blank)."""
    for r in rows:
        if not str(r.get("expected_from_document") or "").strip():
            r["expected_from_document"] = NO_VALUE
    return rows
