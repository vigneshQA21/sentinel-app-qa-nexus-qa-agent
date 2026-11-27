"""Incoterm: where the value may come from, and how the selected value is shown (user, 26 Nov 2026, IPA/11/2026-27).

* Source: Nexus may take the House Incoterm from the shipment's invoice ("Incoterm · From Invoice"): CIF is not on the HBL but the
  commercial invoice prints "CIF NAGOYA". The code is checked on the bill first, then on the invoice / debit note of the sample.
* Display: the selected value must show only the code ("CIF"); the full wording ("CIF – Cost, Insurance And Freight") belongs in the
  dropdown list only. Same for the Invoice / Packing List panels' Incoterm, across the application. A long selected text = FAIL."""
from __future__ import annotations

import re

INCOTERMS = r"(EXW|FCA|FAS|FOB|CFR|CIF|CPT|CIP|DAP|DPU|DDP|DAT)"
PLACEHOLDER = re.compile(r"^\s*(?:select(?:\s+option)?|choose\b.*|-+)?\s*$", re.I)


def code_of(value: str) -> str:
    """'CIF – Cost, Insurance And Freight' -> 'CIF'; '' when the value names no Incoterm."""
    m = re.search(r"(?<![A-Z])" + INCOTERMS + r"(?![A-Z])", (value or "").upper())
    return m.group(1) if m else ""


def printed(code: str, text: str) -> bool:
    return bool(code) and re.search(rf"(?<![A-Z]){code}(?![A-Z])", (text or "").upper()) is not None


def fix_value_rows(rows: list[dict], bill_text: str, other_docs: list[tuple[str, str]]) -> None:
    """Incoterm rows judged by the bill only: PASS when the code is printed on the bill, or on another document of the shipment
    (other_docs = [(where, text)], e.g. the commercial invoice). Rows whose code is nowhere stay as they are."""
    for r in rows:
        if (r.get("label") or "").strip().lower() != "incoterm" or r.get("result") == "PASS":
            continue
        code = code_of(r.get("shown_in_nexus", ""))
        if not code:
            continue
        if printed(code, bill_text):
            r.update(result="PASS", expected_from_document=f"{code} (printed on the bill)",
                     note=f"the code {code} is printed on the bill | {r.get('note', '')}".strip(" |"))
            continue
        hit = next((w for w, t in other_docs if printed(code, t)), None)
        if hit:
            r.update(result="PASS", expected_from_document=f"{code} (not on the bill; printed on {hit})",
                     note=f"Nexus takes the Incoterm from the invoice ('Incoterm · From Invoice'): {code} is printed on {hit}")


def display_row(value: str, section: str, tag: str | None = None) -> list[dict]:
    """One row: the Incoterm is the dropdown (full wording in the list) and the selected value shows only its code.
    tag = the field's HTML tag when known: anything but SELECT means a free-text box where the dropdown is expected
    (the Invoice panel, IPA/11/2026-27). [] when the field is empty / a placeholder or names no Incoterm."""
    v = (value or "").strip()
    code = code_of(v)
    if PLACEHOLDER.match(v) or not code:
        return []
    row = {"section": section, "label": "Incoterm (selected value)", "field": f"{section} · Incoterm (selected value)",
           "expected_from_document": f"the Incoterm dropdown, showing only the code '{code}' once selected (full wording only in the list)",
           "shown_in_nexus": v, "result": "PASS", "note": ""}
    if tag and tag.upper() != "SELECT":
        row.update(shown_in_nexus=f"{v} (a free-text box, not the Incoterm dropdown)", result="FAIL",
                   note="the Incoterm here is a text box; it should be the same Incoterm dropdown as the House "
                        "(user, 26-Nov-2026: the dropdown applies to the Invoice and across the application)")
    elif re.sub(r"\s+", "", v).upper() != code:
        row.update(result="FAIL", note="the selected Incoterm shows the full dropdown wording; it should show only the code "
                                       "(user, 26-Nov-2026: applies to House, Invoice and every Incoterm dropdown)")
    return [row]
