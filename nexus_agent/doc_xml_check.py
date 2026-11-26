"""Debit Notes must not reach CargoWise through the Master Document XML (Japan bug sheet Sl 19, Enhancement, 26 Nov 2026).

Nexus pushes the documents of a job as 'NEXUS PUSH DOC' XML files (UniversalShipment): DataTarget Type ForwardingConsol = the Master's
documents, ForwardingShipment = a House's. Every AttachedDocument carries FileName, Type Code / Description and the PDF itself
(ImageData, base64). A document is a Debit Note when:
  * its own PDF says so: titled DEBIT NOTE, or an INVOICE with a LOGISTEED party on it (debit_rule.is_agent_bill), or
  * Nexus labelled it so: Type Description / Code or FileName says Debit Note / DN.
The PDF is read, so the check does not depend on Nexus's type codes (an agent debit note pushed as 'INV' is still caught).
Rows use the field-row shape of the other checkers: {section, field, expected_from_document, shown_in_nexus, result, note}."""
from __future__ import annotations

import base64
import re

from .debit_rule import is_agent_bill

SECTION = "CargoWise XML · Master documents"
DN_LABEL = re.compile(r"\bDEBIT\s*NOTE\b|\bDEBITNOTE\b|(?<![A-Z])DN(?![A-Z])|\bDBN\b", re.I)
DN_TITLE = re.compile(r"\bDEBIT\s+NOTE\b", re.I)


def _row(field: str, expected: str, shown: str, result: str, note: str = "") -> dict:
    return {"section": SECTION, "label": field, "field": f"{SECTION} · {field}", "expected_from_document": expected,
            "shown_in_nexus": shown, "result": result, "note": note}


def _pdf_pages(data: bytes) -> list[str]:
    try:
        from .pdf_split import page_texts_layout
        return page_texts_layout(data, ocr=False)
    except Exception:
        return []


def classify_attachment(doc, billed_to, starts) -> tuple[bool, str]:
    """(is a debit note, why) for one AttachedDocument element."""
    name = doc.findtext("{*}FileName") or ""
    code = doc.findtext("{*}Type/{*}Code") or ""
    desc = doc.findtext("{*}Type/{*}Description") or ""
    data = (doc.findtext("{*}ImageData") or "").strip()
    pages = []
    if data:
        try:
            pages = _pdf_pages(base64.b64decode(data))
        except Exception:
            pages = []
    head = "\n".join([l for l in (pages[0] if pages else "").splitlines() if l.strip()][:20])
    if pages and DN_TITLE.search(head):
        return True, "the PDF is titled DEBIT NOTE"
    if any(is_agent_bill(t, billed_to, starts) for t in pages):
        return True, "the PDF is an INVOICE with a LOGISTEED party on it (= Debit Note)"
    for what, val in (("type description", desc), ("type code", code), ("file name", name)):
        if val and DN_LABEL.search(val):
            return True, f"Nexus labelled it a Debit Note ({what} '{val}')"
    return False, ""


def check_master_doc_xml(xmls: dict[str, bytes], billed_to=("LOGISTEED",), starts=("LOGISTEED",)) -> list[dict]:
    """Rows for every 'NEXUS PUSH DOC' XML of the Master (ForwardingConsol): one FAIL per Debit Note attached, else one PASS listing
    what was sent. NOT_RUN when no Master document XML was given."""
    from lxml import etree
    rows: list[dict] = []
    masters = 0
    for fname, data in sorted(xmls.items()):
        try:
            root = etree.fromstring(data if isinstance(data, bytes) else data.encode("utf-8"))
        except Exception as exc:
            rows.append(_row("XML is well-formed", "valid XML", f"{fname}: {type(exc).__name__}", "FAIL", "the file could not be parsed"))
            continue
        trig = " ".join((e.text or "") for e in root.iter("{*}TriggerDescription")).upper()
        targets = [(t.findtext("{*}Type") or "", t.findtext("{*}Key") or "") for t in root.iter("{*}DataTarget")]
        if "PUSH DOC" not in trig or not any(t == "ForwardingConsol" for t, _ in targets):
            continue                                                       # a House document XML or a job XML: not judged here
        masters += 1
        key = next((k for t, k in targets if t == "ForwardingConsol"), "")
        docs = list(root.iter("{*}AttachedDocument"))
        sent = []
        for d in docs:
            name = d.findtext("{*}FileName") or "(no file name)"
            code = d.findtext("{*}Type/{*}Code") or ""
            sent.append(f"{name} [{code}]" if code else name)
            dn, why = classify_attachment(d, billed_to, starts)
            if dn:
                rows.append(_row(f"Debit Note not sent ({name})", "no Debit Note in the Master Document XML",
                                 f"{fname} (Consol {key}): {name}, type {code or '-'} {d.findtext('{*}Type/{*}Description') or ''}".strip(),
                                 "FAIL", f"a Debit Note was pushed to CargoWise with the Master documents: {why}"))
        if not any(r["result"] == "FAIL" and fname in r["shown_in_nexus"] for r in rows):
            rows.append(_row("No Debit Note in the Master Document XML", "no Debit Note", f"{fname} (Consol {key}): {', '.join(sent) or 'no documents'}",
                             "PASS", f"{len(docs)} document(s) checked by their PDF and their Nexus type"))
    if not masters:
        rows.append(_row("Master Document XML given", "a 'NEXUS PUSH DOC' file for the Consol", "not given", "NOT_RUN",
                         "push the job, then put the pushed XML files in samples/<case>/xml (or pass --xml)"))
    return rows
