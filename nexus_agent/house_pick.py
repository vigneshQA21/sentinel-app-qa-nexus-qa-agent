"""Which House (or Master) record of a pre-alert to validate, and which ones are extra (standard for every checker, all tenants).

A pre-alert can list several House rows. The checker validates the House whose bill number is the sample's HBL (or is printed on the
sample's House pages); a House whose bill is empty ("Enter No") or not in the sample is not compared with the House document but
reported as a separate finding: Nexus created a House the sample does not have (e.g. from the terms page of the MBL).
Never the first row by position: the first row can be the extra one (IPA/11/2026-27, 26 Nov 2026)."""
from __future__ import annotations

import re

from .docextract import PLACEHOLDER


def key(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def real_bill(bill: str) -> bool:
    return bool(key(bill)) and not PLACEHOLDER.match(bill or "")


def in_sample(bill: str, expected: list[str], printed_text: str = "") -> bool:
    """The bill is one of the sample's bills, or printed on the sample's pages (punctuation ignored: GFSL-HKG/NGO-26003 = GFSLHKG/NGO26003)."""
    k = key(bill)
    if not real_bill(bill):
        return False
    if any(k == key(e) for e in expected if real_bill(e)):
        return True
    return len(k) >= 6 and k in key(printed_text)


def choose(records: list[dict], kind: str, expected: list[str] | None = None, printed_text: str = "", pick: str = "") -> tuple[dict | None, list[dict]]:
    """(record to validate, extra records) among the rows of `kind` ('House' / 'Master').
    Order: the bill asked for (pick) -> a bill of the sample -> the first row with a real bill -> the first row.
    Extra = every other row that is not a bill of the sample (only judged when the sample's bills are known; an empty bill is always extra)."""
    expected = [e for e in (expected or []) if e]
    rows = [r for r in records if (r.get("Record Type") or "").startswith(kind)]
    if not rows:
        return None, []
    known = bool(expected) or bool(key(printed_text))
    chosen = (next((r for r in rows if pick and key(r.get("Bill No.")) == key(pick)), None)
              or next((r for r in rows if in_sample(r.get("Bill No.", ""), expected, printed_text)), None)
              or next((r for r in rows if real_bill(r.get("Bill No.", ""))), None)
              or rows[0])
    extras = [r for r in rows if r is not chosen and (not real_bill(r.get("Bill No.", ""))
                                                      or (known and not in_sample(r.get("Bill No.", ""), expected, printed_text)))]
    return chosen, extras


def parent_for(options: list[str], kind: str, rec: dict | None) -> str | None:
    """The viewer's parent for the chosen record: 'House (GFSLHKG/NGO26003)'; a record without a bill is shown as 'House 1'."""
    mine = [o for o in options if o.startswith(kind)]
    bill = (rec or {}).get("Bill No.", "")
    if real_bill(bill):
        hit = next((o for o in mine if key(bill) and key(bill) in key(o)), None)
        if hit:
            return hit
    with_bill = [o for o in mine if "(" in o]
    return (with_bill or mine or [None])[0]


def extra_rows(extras: list[dict], kind: str, sample_bills: list[str]) -> list[dict]:
    """One FAIL row per extra record: Nexus created a House the sample does not have."""
    out = []
    sample = ", ".join(b for b in sample_bills if b) or "the sample's House document"
    for r in extras:
        bill = r.get("Bill No.", "")
        shown = (f"Bill No. '{bill or '(empty)'}'" + ("" if real_bill(bill) else " (empty)") +
                 f", Shipper '{r.get('Shipper') or '(empty)'}', Consignee '{r.get('Consignee') or '(empty)'}'"
                 f", Pages '{r.get('Page Nos.') or ''}', Status '{r.get('Status') or ''}'")
        out.append({"section": "Pre-alert", "label": f"Additional {kind}", "field": f"Pre-alert · additional {kind}",
                    "expected_from_document": f"only {sample} (the sample has no other {kind})",
                    "shown_in_nexus": shown, "result": "FAIL",
                    "note": f"Nexus created a {kind} that is not in the sample (empty bill / not printed on the sample's {kind} pages); "
                            f"open it in the viewer to see which page it was made from"})
    return out
