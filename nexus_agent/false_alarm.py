"""False-alarm guard: the last step of every field check, run just before the verdict.

Standing order (user, 27 Nov 2026): "don't create false alarms". A FAIL / REVIEW is only reported as a possible bug when the checker's own
reading is trustworthy. Every rule below comes from a false alarm that really happened; each one re-labels the row and says why in the
note, so nothing is hidden:
  - the checker could not read the document value  -> NOT_VERIFIABLE (never a bug, never a pass)
  - the difference is not a data difference        -> INFO / PASS with the reason
Real bugs are kept: a location code that names ANOTHER place (BDQ for Vado Ligure, MXF for Malpensa) stays FAIL.
"""
from __future__ import annotations

import re

GUARD = "checker guard"

# 1) values the checker took from a label, a clause, a placeholder or the cargo block instead of the field's own box
#    (Dubai 27 Nov: Shipper = 'FREIGHT PREPAID Applicable free time ...', Port Of Discharge = 'AGENT', Vessel = 'AND VOYAGE NO (see Clause 8 & 9)',
#    Date = 'SHIPPED ON BOARD DATE', Shipper = '902 CARTONS 6,283.200KGS 64.343 CBM ====')
_LABEL_TEXT = re.compile(r"APPLICABLE FREE TIME|\bSEE CLAUSE\b|\bCLAUSE \d|VOYAGE NO\b|SHIPPED ON BOARD|NOTIFY PARTY|PORT OF (LOADING|DISCHARGE)|"
                         r"PLACE OF (RECEIPT|DELIVERY)|TERMS AND CONDITIONS|={3,}|DETENTION|DEMURRAGE", re.IGNORECASE)
_FREIGHT_WORDS = re.compile(r"\bFREIGHT (PREPAID|COLLECT)\b", re.IGNORECASE)
_CARGO_BLOCK = re.compile(r"\d[\d,.]*\s*(KGS?|CBM|CARTONS?|PKGS?|PALLETS?)\b", re.IGNORECASE)
_PLACEHOLDERS = {"SELECT", "SELECT BRANCH", "ENTER NO", "AGENT", "SHIPPER", "CONSIGNEE", "-", "N/A"}
# 2) 'no value' wordings of the document side
_NO_DOC_VALUE = re.compile(r"^\(?(no value found in the document|not available in the document|not found in the scan|not found on the document|"
                           r"address on the document|printed on the document|found on the document)",
                           re.IGNORECASE)
# 3) workflow fields: Nexus's processing state, not data printed on a document
_WORKFLOW = {"status", "job number", "tms status", "cw status", "job progress"}
# 4) flight / voyage numbers printed after a place name ('DUBAI EK092-301026', 'DUBAI EY0086-011126 EY9149-021126')
_FLIGHT_TAIL = re.compile(r"^(?:\s+[A-Z0-9]{2}\s?\d{2,4}(?:[-/]\d{4,6})?)+\s*$")
# 5) identifiers a document can list several of: Nexus showing ONE of them is not a mismatch
_MULTI_ID = {"container no", "container number", "seal no", "seal number"}
_CONTAINER = re.compile(r"\b[A-Z]{4}\d{7}\b")
# 6) location codes, for fields that show a code where the document prints the name (KLF = Khor Fakkan). Unknown code -> NOT_VERIFIABLE,
#    a code of another place stays FAIL with that place named. Extend in settings: validation.location_codes {CODE: [names]}.
LOCATION_CODES = {
    "KLF": ["Khor Fakkan", "Khor Al Fakkan"], "JEA": ["Jebel Ali"], "DXB": ["Dubai"], "AUH": ["Abu Dhabi"], "SHJ": ["Sharjah"],
    "DWC": ["Dubai World Central", "Al Maktoum"], "AJM": ["Ajman"], "BDQ": ["Vadodara", "Baroda"], "VDL": ["Vado Ligure"],
    "GOA": ["Genoa", "Genova"], "SPE": ["La Spezia"], "MXP": ["Milan Malpensa", "Malpensa"], "LIN": ["Milan Linate", "Linate"],
    "MXF": ["Montgomery", "Maxwell"], "CDG": ["Paris Charles de Gaulle", "Paris CDG", "Roissy"], "PAR": ["Paris"], "NRT": ["Narita"],
    "HND": ["Haneda"], "TYO": ["Tokyo"], "NGO": ["Nagoya"], "UKB": ["Kobe"], "OSA": ["Osaka"], "KIX": ["Kansai"], "YOK": ["Yokohama"],
    "SHA": ["Shanghai"], "PVG": ["Shanghai Pudong"], "HKG": ["Hong Kong"], "SIN": ["Singapore"], "MAA": ["Chennai", "Madras"],
    "BOM": ["Mumbai", "Bombay"], "NSA": ["Nhava Sheva", "JNPT"], "DEL": ["Delhi"], "BLR": ["Bengaluru", "Bangalore"],
}
_CODE_FIELD = re.compile(r"(pol|pod|ctn pol|ctn pod)\s*city|^(from|to)$|port code|airport code", re.IGNORECASE)


def _garbled(text: str) -> bool:
    """Rotated / spaced-out print read letter by letter: 'IL ES T CO NV EN U QU E LE S MA RC HA ND'."""
    toks = text.split()
    return len(toks) >= 6 and sum(1 for t in toks if len(t) <= 2) / len(toks) >= 0.7


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper()).split())


def _label(r: dict) -> str:
    return (r.get("label") or str(r.get("field", "")).split("·")[-1]).strip().lower()


def _set(r: dict, result: str, why: str) -> None:
    r["note"] = (r.get("note") + "  " if r.get("note") else "") + f"[{GUARD}: {why}]"
    r["result"] = result


def _codes(extra: dict | None) -> dict[str, list[str]]:
    out = {k: list(v) for k, v in LOCATION_CODES.items()}
    for k, v in (extra or {}).items():
        out.setdefault(str(k).upper(), []).extend([v] if isinstance(v, str) else list(v))
    return out


def guard(rows: list[dict], doc_text: str = "", location_codes: dict | None = None) -> list[dict]:
    """Re-labels FAIL / REVIEW rows whose difference comes from the checker, not from Nexus. Mutates and returns `rows`."""
    codes = _codes(location_codes)
    for r in rows:
        if r.get("result") not in ("FAIL", "REVIEW"):
            continue
        label = _label(r)
        doc = " ".join(str(r.get("expected_from_document", "")).split())
        shown = " ".join(str(r.get("shown_in_nexus", "")).split())
        if not doc:                     # blank = the checker has no reading (e.g. a scan): never decided here, the row stays as it is
            continue
        if label in _WORKFLOW:          # a job stuck in a status can be a real bug (REG-001 was logged once): check by eye, not a data diff
            _set(r, "NOT_VERIFIABLE", "workflow status of the job, not a value printed on the document: check by eye if it looks stuck")
            continue
        if _NO_DOC_VALUE.match(doc):
            _set(r, "INFO", "the document prints no value for this field: nothing to compare (Nexus value shown for reference)"
                 if shown else "empty on both sides")
            continue
        if doc.upper() in _PLACEHOLDERS:
            _set(r, "NOT_VERIFIABLE", f"the checker read a placeholder / label ('{doc}') instead of the field's box")
            continue
        cands = [c.strip() for c in doc.split(",") if c.strip()]
        if len(cands) >= 2 and all(re.fullmatch(r"[\d\- ]{3,}", c) for c in cands) and shown and shown not in cands:
            _set(r, "NOT_VERIFIABLE", f"the checker found several candidate values ({doc}) and could not tell which box is this field")
            continue
        if label == "name" and shown and re.search(r"\d", doc) and not re.search(r"\d", shown) and len(doc.split()) >= len(shown.split()) + 3:
            _set(r, "NOT_VERIFIABLE", "the checker's name box ran into the address lines (digits / place names after the name)")
            continue
        if _garbled(doc):
            _set(r, "NOT_VERIFIABLE", "the document text at this box is read letter by letter (rotated or spaced print): unreadable")
            continue
        if _LABEL_TEXT.search(doc) or (_FREIGHT_WORDS.search(doc) and "freight" not in label) or \
                (_CARGO_BLOCK.search(doc) and any(w in label for w in ("shipper", "consignee", "name", "address", "notify"))):
            _set(r, "NOT_VERIFIABLE", "the checker took text from another box (clause, label or cargo block), not this field's value")
            continue
        if shown and doc.upper().startswith(shown.upper()) and len(doc) > len(shown) and _FLIGHT_TAIL.match(doc[len(shown):].upper()):
            _set(r, "PASS", "same place; the document also prints the flight / voyage number after it")
            continue
        if label in _MULTI_ID:
            listed = set(_CONTAINER.findall((doc_text or "").upper())) | set(_CONTAINER.findall(doc.upper()))
            if shown and shown.upper() in listed and len(listed) > 1:
                _set(r, "INFO", f"the document lists {len(listed)} ({', '.join(sorted(listed))}); Nexus shows {shown}, one of them")
                continue
        if _CODE_FIELD.search(label) and re.fullmatch(r"[A-Z]{3}", shown or "") and not re.fullmatch(r"[A-Z]{3}", doc.upper()):
            names = codes.get(shown)
            if not names:
                _set(r, "NOT_VERIFIABLE", f"Nexus shows the code {shown}, the document the name '{doc}'; {shown} is not in the location table "
                                          f"(add it under validation.location_codes)")
            elif any(_norm(n) in _norm(doc) or _norm(doc) in _norm(n) for n in names):
                _set(r, "PASS", f"{shown} is the code of {names[0]}")
            else:
                r["note"] = (r.get("note") + "  " if r.get("note") else "") + f"[{GUARD}: {shown} is the code of {names[0]}, not of '{doc}']"
                r["result"] = "FAIL"
            continue
    return rows
