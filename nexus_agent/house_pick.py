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


_AWB = re.compile(r"(?<!\d)(\d{3})[\s-]*(?:[A-Z]{2,3}[\s-]*)?(\d{4})[\s-]?(\d{4})(?!\d)")


def awb_numbers(text: str) -> set[str]:
    """11-digit air waybill numbers printed in a text ('123 MI 4567 8901', '123-45678901', '12345678901')."""
    return {"".join(m.groups()) for m in _AWB.finditer((text or "").upper())}


def consolidation_map(samples_dir, case_id: str, extra_bills: list[str]) -> dict[str, tuple[str, str]]:
    """{extra House bill: (other case, MAWB)} when another sample of this tenant prints that House number AND a MAWB that this case's own
    sample prints too: Nexus joined two Houses of one MAWB in one pre-alert = correct consolidation (user, 27 Nov 2026: DXB-009 + DXB-011,
    both HAWBs print MAWB 123-45678901 -> 'not a bug, it's expected')."""
    import subprocess
    from pathlib import Path
    root = Path(samples_dir)
    def text(pdf: Path) -> str:
        try:
            return subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, timeout=60).stdout
        except Exception:
            return ""
    own = set()
    for pdf in sorted((root / case_id).glob("*.pdf")) if (root / case_id).is_dir() else []:
        own |= awb_numbers(text(pdf))
    out: dict[str, tuple[str, str]] = {}
    wanted = {key(b): b for b in extra_bills if real_bill(b)}
    if not own or not wanted:
        return out
    for folder in sorted(x for x in root.iterdir() if x.is_dir() and x.name != case_id and not x.name.startswith(("_", "."))):
        for pdf in sorted(folder.glob("*.pdf")):
            t = text(pdf)
            flat = key(t)
            for k, b in wanted.items():
                if b not in out and k in flat:
                    shared = own & awb_numbers(t)
                    if shared:
                        out[b] = (folder.name, sorted(shared)[0])
    return out


def extra_rows(extras: list[dict], kind: str, sample_bills: list[str], consol: dict[str, tuple[str, str]] | None = None) -> list[dict]:
    """One FAIL row per extra record: Nexus created a House the sample does not have. An extra House of the SAME MAWB (another sample prints
    its number and this case's MAWB; `consol` from consolidation_map) is expected consolidation: INFO, not FAIL."""
    out = []
    sample = ", ".join(b for b in sample_bills if b) or "the sample's House document"
    for r in extras:
        bill = r.get("Bill No.", "")
        if consol and bill in consol:
            other, mawb = consol[bill]
            m = f"{mawb[:3]}-{mawb[3:]}"
            out.append({"section": "Pre-alert", "label": f"Additional {kind}", "field": f"Pre-alert · additional {kind}",
                        "expected_from_document": f"{bill}: House of the same MAWB {m} (sample {other})",
                        "shown_in_nexus": f"Bill No. '{bill}' in this pre-alert", "result": "INFO",
                        "note": f"expected consolidation: both Houses print MAWB {m}, so Nexus joins them in one pre-alert"})
            continue
        shown = (f"Bill No. '{bill or '(empty)'}'" + ("" if real_bill(bill) else " (empty)") +
                 f", Shipper '{r.get('Shipper') or '(empty)'}', Consignee '{r.get('Consignee') or '(empty)'}'"
                 f", Pages '{r.get('Page Nos.') or ''}', Status '{r.get('Status') or ''}'")
        out.append({"section": "Pre-alert", "label": f"Additional {kind}", "field": f"Pre-alert · additional {kind}",
                    "expected_from_document": f"only {sample} (the sample has no other {kind})",
                    "shown_in_nexus": shown, "result": "FAIL",
                    "note": f"Nexus created a {kind} that is not in the sample (empty bill / not printed on the sample's {kind} pages); "
                            f"open it in the viewer to see which page it was made from"})
    return out
