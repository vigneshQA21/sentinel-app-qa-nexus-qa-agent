"""What the document prints for one field, as a value (rule, 26 Nov 2026: "Document says" is never blank).

Order of evidence for a field:
  1. a labelled value: the text after the field's label on the document (VESSEL / PORT OF LOADING / PLACE AND DATE OF ISSUE / ...),
     or a value of a recognisable form (container number, container type, weight in KGS, volume in CBM, FREIGHT PREPAID/COLLECT, Incoterm);
  2. the document line that best matches the value Nexus shows (said so: "matching line");
  3. NO_VALUE ("no value found in the document").
Each result says where it was read (label / form / line), so the report can show the document value next to the Nexus value."""
from __future__ import annotations

import re

from .docvalue import BLANK

NO_VALUE = "no value found in the document"

DATE_RX = (r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[-./ ](?:\d{1,2}|[A-Za-z]{3,9})[-./ ]\d{2,4}\b|"
           r"\b[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}\b")

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
    (r"^bill no\.?$|^b/?l no\.?$|^air waybill number$|^house number", [r"B/L\s*(?:NO\.?|NUMBER)", r"BILL OF LADING\s*(?:NO\.?|NUMBER)", r"BILL\s*/\s*LADING\s*(?:NO\.?|NUMBER)",
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


PLACEHOLDER = re.compile(r"^\s*(?:enter\b.*|select(?:\s+option)?|choose\b.*|-+)\s*$", re.I)

# value shape a labelled value must have (otherwise the next candidate is tried)
SHAPE = {r"^seal( no\.?)?\d*$": r"[A-Z]{2,}\d{4,}|\d{6,}", r"^bill no\.?$|^b/?l no\.?$": r"\b(?=[A-Z0-9-]*\d)(?=[A-Z0-9-]*[A-Z])[A-Z0-9-]{6,}\b|\b\d{8,}\b",
         r"^booking( no\.?)?$": r"\d{4,}|[A-Z]{2,}\d{3,}", r"^voyage( no\.?| number)?$": r"\d"}


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _after_label(lines: list[str], pattern: str, shape: str = "") -> str:
    """Text after the label on its line; the next line when the label stands alone (a box heading). With `shape`, only a value of
    that shape counts (SEAL NO.: OOLJYY0948, not 'NO.: I')."""
    rx = re.compile(r"(?<![A-Za-z])" + pattern + r"(?![A-Za-z])\s*[:：/.\-]?\s*", re.IGNORECASE)   # whole words: SHIPPING LINE is not inside LINES
    for i, ln in enumerate(lines):
        m = rx.search(ln)
        if not m:
            continue
        rest = ln[m.end():].strip(" :：-")
        nxt = lines[i + 1][:100] if i + 1 < len(lines) else ""
        if shape:
            for cand in (rest, nxt):
                hit = re.search(shape, cand or "")
                if hit:
                    return hit.group(0)
            continue
        if len(rest) >= 2 and not re.fullmatch(r"[\W_]+", rest):
            return rest[:100]
        if nxt:
            return nxt
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
BOX_FOR = [(r"^vessel( name)?$", "vessel"), (r"^voyage( no\.?| number)?$", "voyage"), (r"^port of loading$|^ctn pol city$", "port of loading"),
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
        boxes = src["small_boxes"]
        if key == "voyage" and key not in boxes and "vessel" in boxes:
            vv, pg = boxes["vessel"]
            voy = split_voyage(vv)[1]
            if voy:
                return voy, f"by position: the voyage printed in the box 'VESSEL' ('{vv}') on page {pg}"
        if key == "date of issue" and key not in boxes and "place of issue" in boxes and boxes["place of issue"][0] != BLANK:
            pv, pg = boxes["place of issue"]
            d = re.search(DATE_RX, pv)
            if d:
                return d.group(0), f"by position: the date printed in the box 'PLACE AND DATE OF ISSUE' ('{pv}') on page {pg}"
        if key == "final destination" and key not in boxes and "place of delivery" in boxes:
            key = "place of delivery"
        if key == "place of issue" and key in boxes and boxes[key][0] != BLANK and not re.search(r"[A-Za-z]{3,}", re.sub(DATE_RX, "", boxes[key][0])):
            v, pg = boxes[key]
            return f"{NO_VALUE} (the box 'PLACE AND DATE OF ISSUE' on page {pg} prints only the date {v})", f"by position: the box on page {pg} prints only a date"
        if key in boxes:
            v, pg = boxes[key]
            if v == BLANK:
                return f"{NO_VALUE} (the box '{key.upper()}' on page {pg} is blank)", f"by position: the box '{key.upper()}' on page {pg} is blank"
            if key == "vessel":
                name, voy = split_voyage(v)
                if voy:
                    return name, f"by position from the box 'VESSEL' on page {pg} (prints '{v}'; voyage {voy})"
            return v, f"by position from the box '{key.upper()}' on page {pg}"
    if PLACEHOLDER.match(value or ""):
        value = ""                                                        # 'Enter No' / 'Select option': Nexus shows an empty field
    v, how = extract(label, value, src.get("text", ""))
    if how == "matching line on the document" and src.get("pdf") and not src.get("scanned"):
        cell = matching_cell(_layout_cells(src), value)
        if cell:
            v, how = cell, "the cell printing this value on the document (this bill has no printed label for it)"
    return _narrow(lab, v, how)


def _narrow(lab: str, v: str, how: str) -> tuple[str, str]:
    """The field's own part of a shared box: vessel / voyage from 'OOCL PORTUGAL / 007E', place from 'HELSINKI, 2026-08-19'."""
    if v.startswith(NO_VALUE):
        return v, how
    if re.search(r"^vessel( name)?$|^voyage( no\.?| number)?$", lab):
        name, voy = split_voyage(v)
        if voy:
            return (name if lab.startswith("vessel") else voy), f"{how}; the box prints '{v}'"
    if re.search(r"^place$|^place of issue$", lab) and re.search(DATE_RX, v) and not re.search(r"[A-Za-z]{3,}", re.sub(DATE_RX, "", v)):
        return f"{NO_VALUE} (the place-and-date box prints only the date {v})", how
    return v, how


def _layout_lines(src: dict) -> list[str]:
    """Lines of the bill pages as laid out (character columns kept), cached on the source."""
    if "layout_lines" not in src:
        out: list[str] = []
        try:
            import pdfplumber
            with pdfplumber.open(str(src["pdf"])) as pdf:
                for no in src.get("pages") or range(1, len(pdf.pages) + 1):
                    if no - 1 < len(pdf.pages):
                        out += (pdf.pages[no - 1].extract_text(layout=True) or "").splitlines() + [""]
        except Exception:
            pass
        src["layout_lines"] = out
    return src["layout_lines"]


NEXT_PARTY = re.compile(r"^(?:NOTIFY|ALSO\s+NOTIFY|CONSIGNEE|SHIPPER|EXPORTER|SAME\s+AS\b|FOR\s+DELIVERY|DELIVERY\s+AGENT|PRE-?CARRIAGE)", re.I)


def party_block(lines: list[str], name: str) -> tuple[str, str]:
    """(name line, address) of the party block that starts with `name`: the lines printed directly below it in the same column,
    up to the first empty line. ('', '') when the name is not printed as the start of a block."""
    want = _tokens(re.sub(r"\s+-\s+\w+$", "", name or ""))                # 'LOGISTEED Express, Ltd. - TYO': drop the branch suffix
    if not want:
        return "", ""
    for i, ln in enumerate(lines):
        for m in re.finditer(r"\S+(?:\s{1,2}\S+)*", ln):                  # cells: runs of text split by 3+ spaces
            if len(want & _tokens(m.group(0))) / len(want) < 0.75:
                continue
            col, addr, gap = m.start(), [], 0
            for nl in lines[i + 1: i + 10]:
                seg = nl[col:].split("   ")[0].strip() if len(nl) > col else ""
                if nl[:col].strip() and col and not nl[col - 1].isspace():
                    break                                                 # text runs into the column from the left: another box
                if not seg:
                    gap += 1
                    if gap > 1 or not addr:
                        break                                             # one blank line inside a block is allowed, two end it
                    continue
                if NEXT_PARTY.match(seg):
                    break                                                 # the next box starts (Notify / SAME AS CONSIGNEE / ...)
                gap = 0
                addr.append(seg)
            return m.group(0).strip(), " ".join(addr)
    return "", ""


def _layout_cells(src: dict) -> list[str]:
    """Text cells of the bill pages as laid out (columns split on wide gaps), cached on the source."""
    if "layout_cells" not in src:
        cells: list[str] = []
        try:
            import pdfplumber
            with pdfplumber.open(str(src["pdf"])) as pdf:
                for no in src.get("pages") or range(1, len(pdf.pages) + 1):
                    if no - 1 < len(pdf.pages):
                        for ln in (pdf.pages[no - 1].extract_text(layout=True) or "").splitlines():
                            cells += [c.strip() for c in re.split(r"\s{3,}", ln) if c.strip()]
        except Exception:
            pass
        src["layout_cells"] = cells
    return src["layout_cells"]


def matching_cell(cells: list[str], value: str) -> str:
    """The shortest cell holding every word of the Nexus value (or most of them), else ''."""
    want = _tokens(value)
    if not want:
        return ""
    scored = [(len(want & _tokens(c)) / len(want), -len(c), c) for c in cells]
    scored = [x for x in scored if x[0] >= 0.5]
    return max(scored)[2][:120] if scored else ""


VOYAGE_TOKEN = re.compile(r"^(?:V\.?\s?)?[A-Z]?\d{2,4}[A-Z]{0,2}$")


def split_voyage(box: str) -> tuple[str, str]:
    """'OOCL PORTUGAL 007E' -> ('OOCL PORTUGAL', '007E'); ('ONE RELIABILITY', '') when the box has no voyage token at the end."""
    parts = (box or "").replace(" / ", " ").replace("/", " / ").split()
    parts = [x for x in parts if x != "/"]
    if len(parts) >= 2 and VOYAGE_TOKEN.match(parts[-1].upper()) and re.search(r"[A-Za-z]{3,}", " ".join(parts[:-1])):
        return " ".join(parts[:-1]), parts[-1]
    return box, ""


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[A-Z0-9]+", (s or "").upper()) if len(t) > 1}


def matching_line(text: str, value: str) -> str:
    """The document line, or the smallest block of up to 4 consecutive lines (an address), sharing most words with the Nexus value
    (at least half of them), else ''."""
    want = _tokens(value)
    if not want:
        return ""
    lines = _lines(text)
    best, score = "", 0.0
    for size in (1, 2, 3, 4):                                            # a bigger block must hold MORE of the value to win
        for i in range(len(lines) - size + 1):
            block = " ".join(lines[i:i + size])
            s = len(want & _tokens(block)) / len(want)
            if s > score + 1e-9:
                best, score = block, s
    return best[:200] if score >= 0.5 else ""


def extract(label: str, value: str, text: str) -> tuple[str, str]:
    """(document value, how it was found) for one field; (NO_VALUE, '') when the document has nothing for it."""
    lab = (label or "").strip().lower()
    lines = _lines(text)
    upper = "\n".join(lines).upper()
    for lab_rx, doc_labels in LABELS:
        if re.search(lab_rx, lab):
            shape = next((sh for rx_, sh in SHAPE.items() if re.search(rx_, lab)), "")
            for dl in doc_labels:
                v = _after_label(lines, dl, shape)
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
