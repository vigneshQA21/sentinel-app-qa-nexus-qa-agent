"""Manifest, Invoice and Packing List data checks: what Nexus extracted for each document against the document itself.
These documents have no fixed layout, so: key fields are read from the document by their label and compared exactly;
every other value Nexus shows must appear on the document; a field Nexus left empty although the document has the
value is a FAIL."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

import pdfplumber

from .config import Config
from .local_sender import LocalSender
from .master_check import _text, norm, num, parse_date, row, tokens
from .nexus.session import NexusSession, SessionExpired
from .nexus.uat import UatPages, open_document_page, read_panel_fields
from .pdf_split import detect_parts, page_texts
from .store import Store
from .testsuite import Case, sample_files
from .validate import _buffer, plan_wait

log = logging.getLogger(__name__)
CURRENCY_SIGNS = {"USD": ("US$", "US $", "$"), "EUR": ("€",), "GBP": ("£",), "JPY": ("¥",), "INR": ("₹", "Rs.", "Rs "), "CNY": ("RMB", "CN¥")}
MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
ID_TAIL = r"([A-Z0-9][A-Z0-9/-]{3,})"

# label in Nexus -> (kind of value, regex that reads the same value from the document or None)
INVOICE = {
    "Invoice Number": ("id", re.compile(r"(?:Document\s*Number|Invoice\s*(?:No\.?|Number|#))\s*[:.]?\s*" + ID_TAIL, re.I)),
    "Invoice Date": ("date", re.compile(r"(?:Document\s*Date|Invoice\s*Date)\s*[:.]?\s*(\d{1,2}\s*[A-Za-z]{3,9}\s*\d{2,4}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})", re.I)),
    "Grand Total": ("amount", re.compile(r"(?:Total\s*Amount\s*of\s*invoice|Grand\s*Total|Invoice\s*Total)\s*[:.]?\s*([\d.,]+)", re.I)),
    "Currency Code": ("code", re.compile(r"Currency\s*[:.]?\s*([A-Z]{3})\b")),
    "Po Number": ("id", None), "Order No": ("id", None), "Account No": ("id", None), "Customer No": ("id", None),
    "Delivery No": ("id", None), "Supplier No": ("id", None), "Reference No": ("id", None),
    "Gross Weight": ("weight", None), "Incoterm": ("code", None),
}
PACKING = {
    "Packing List No": ("id", re.compile(r"^\s*Document\s*Number\s+(\S.*?)\s*$", re.I | re.M)),
    "Date": ("date", re.compile(r"^\s*Document\s*Date\s+(\S.*?)\s*$", re.I | re.M)),
    "Invoice No": ("id", None), "Order No": ("id", None), "Po Number": ("id", None), "Customer No": ("id", None),
    "Supplier No": ("id", None), "Account No": ("id", None),
    "Gross Weight": ("weight", re.compile(r"Total\s*Gross\s*Weight\s*[:.]?\s*([\d.,]+)", re.I)),
    "Incoterm": ("code", None),
}
MANIFEST = {
    "Master Air Waybill": ("id", re.compile(r"Air\s*Freight\s*Manifest\s*-\s*(\d{3}-\d{8})", re.I)),
    "Air Waybill No": ("id", re.compile(r"HAWB\s*:\s*" + ID_TAIL, re.I)),
    "Pieces": ("count", re.compile(r"Packs\s*:\s*(\d+)", re.I)),
    "Weight": ("weight", re.compile(r"\bWeight\s*:\s*([\d.,]+)\s*KG", re.I)),
}
DEBITNOTE = {
    "House Bill No": ("id", re.compile(r"(?:House\s*B/?L|HAWB|H\.?B/?L)\s*(?:No\.?|Number)?\s*[:.]?\s*" + ID_TAIL, re.I)),
    "Master Bill No": ("id", re.compile(r"(?:Master\s*B/?L|MAWB|M\.?B/?L)\s*(?:No\.?|Number)?\s*[:.]?\s*(\d{3}-?\d{8})", re.I)),
    "Invoice No": ("id", None), "Date": ("date", None),
}
SHIPPERDOC = {"Reference No": ("id", None), "Order No": ("id", None), "Po Number": ("id", None), "Invoice No": ("id", None)}
SPECS = {"DEBITNOTE": (DEBITNOTE, ["Shipper", "Consignee"], "DEBITNOTE"), "SHIPPERDOC": (SHIPPERDOC, ["Shipper", "Consignee"], "SHIPPERDOC"),
         "INVOICE": (INVOICE, ["Seller", "Buyer"], "INVOICE"), "PACKING": (PACKING, ["Shipper", "Consignee"], "PACKING"),
         "MANIFEST": (MANIFEST, ["Shipper", "Consignee"], "MANIFEST")}
TITLES = {"DEBITNOTE": "DEBIT NOTE DATA", "SHIPPERDOC": "SHIPPER DOCUMENT DATA", "INVOICE": "INVOICE DATA", "PACKING": "PACKING LIST DATA", "MANIFEST": "MANIFEST DATA"}


PATTERNS = {"INVOICE": "Invoice", "PACKING": r"Packing\s*List", "DEBITNOTE": r"Debit\s*Note|DebitNote",
            "SHIPPERDOC": r"Shipper\s*Doc\w*|ShipperDoc"}


def kinds_for(cfg: Config, case: Case) -> tuple[str, ...]:
    """Manifest, Invoice and Packing List always; Debit Note / Shipper Document when the sample contains them."""
    wanted = (case.docs or "").lower()
    out = [k for k, word in (("MANIFEST", "manifest"), ("INVOICE", "invoice"), ("PACKING", "packing")) if not wanted or word in wanted]   # only what the case lists
    for extra in ("DEBITNOTE", "SHIPPERDOC"):
        try:
            if doc_text(cfg, case, extra):
                out.append(extra)
        except Exception:
            pass
    return tuple(out)


# --- helpers ---------------------------------------------------------------------------------------------
def date_in(raw: str, d: tuple[int, int, int]) -> bool:
    sq = re.sub(r"[\s.,]", "", re.sub("[\u2212\u2013\u2014]", "-", raw).upper())          # 2026−08−14 (a real minus sign) = 2026-08-14
    day, mon, yr = d
    forms = {f"{day:02d}{MON[mon - 1]}{yr}", f"{day}{MON[mon - 1]}{yr}", f"{day:02d}{MON[mon - 1]}{yr % 100:02d}",
             f"{yr}-{mon:02d}-{day:02d}", f"{day:02d}/{mon:02d}/{yr}", f"{day}/{mon}/{yr}", f"{day:02d}-{mon:02d}-{yr}", f"{day:02d}-{MON[mon - 1]}-{yr % 100:02d}",
             f"{day:02d}-{MON[mon - 1].title()}-{yr % 100:02d}".upper(), f"{day:02d}-{MON[mon - 1]}-{yr}", f"{day}-{MON[mon - 1]}-{yr}",
             f"{day:02d}-{mon:02d}-{yr % 100:02d}", f"{yr}/{mon:02d}/{day:02d}", f"{day:02d}/{mon:02d}/{yr % 100:02d}"}
    return any(f.upper() in sq for f in forms)


def find_date(s: str | None) -> tuple[tuple[int, int, int] | None, bool]:
    """(date, clean?) - the first date inside s, and whether s is nothing but that date."""
    exact = parse_date(re.sub(r"\s+", " ", (s or "").strip()))
    if exact and exact[1]:
        return exact, True
    m = re.search(r"(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\s*(\d{4})|(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    if not m:
        return None, False
    if m.group(1):
        mon = MON.index(m.group(2).upper()) + 1 if m.group(2).upper() in MON else 0
        return ((int(m.group(1)), mon, int(m.group(3))) if mon else None), False
    return (int(m.group(4)), int(m.group(5)), int(m.group(6))), False


def amount(s) -> float | None:
    """1,218.41 / 1.218,41 / '1 218,41' / '1 218, 41' -> 1218.41 (the last separator with 1-2 digits after it is the decimal point)."""
    t = re.sub(r"\s+", "", str(s or ""))
    m = re.fullmatch(r"([\d.,]*\d)[.,](\d{1,2})", t)
    if m and re.search(r"[.,]", t) and not re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", t):
        return num(re.sub(r"[.,]", "", m.group(1)) + "." + m.group(2))
    return num(re.sub(r"[,]", "", t))


def amounts_in(raw: str) -> set[float]:
    """Every amount printed in the document text, whatever the number format."""
    found = re.findall(r"\d{1,3}(?:[ \u00a0.,]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?", raw or "")
    return {v for v in (amount(x) for x in found) if v is not None}


def check_value(rtype: str, anchor, ui_value: str, raw: str) -> dict:
    """One Nexus value against the document text. Returns a row (expected / shown / result / note)."""
    sq, nm = re.sub(r"[\s,]", "", raw), norm(raw)
    found = None
    if anchor is not None:
        m = anchor.search(raw)
        found = m.group(1).strip() if m else None
    shown = ui_value.strip()

    if found is not None:                                              # the document states this value explicitly
        if not shown:
            return row("", found, shown, "FAIL", "Nexus left it empty, the document has a value")
        if rtype in ("id", "code"):
            ok = norm(shown) == norm(found)
        elif rtype in ("amount", "weight", "count"):
            ok = amount(shown) is not None and amount(found) is not None and abs(amount(shown) - amount(found)) < 1e-6
        else:                                                           # date
            fd, _ = find_date(found); ud, clean = find_date(shown)
            ok = fd is not None and fd == ud
            if ok and not clean:
                return row("", found, shown, "FAIL", "the date is right but Nexus adds extra text to the value")
        note = "same as the value printed on the document"
        if ok and rtype == "amount" and re.search(r",\s", shown):
            note += f" (Nexus formats it with a space: '{shown}')"
        return row("", found, shown, "PASS" if ok else "FAIL", note if ok else "differs from the document")

    if not shown:                                                       # nothing explicit on the document, nothing in Nexus
        return row("", None, shown, "INFO", "empty in Nexus; no value located on the document")
    if rtype == "id":
        ok = norm(shown) in nm
    elif rtype == "code":
        ok = (bool(tokens(shown)) and tokens(shown) <= tokens(raw)) or (len(norm(shown)) >= 3 and norm(shown) in nm)
        if not ok and shown.strip().upper() in CURRENCY_SIGNS:          # a currency code printed as a sign: USD -> US$
            ok = any(sign in raw for sign in CURRENCY_SIGNS[shown.strip().upper()])
    elif rtype == "amount":
        ok = amount(shown) is not None and (f"{amount(shown):.2f}" in sq or any(abs(a - amount(shown)) < 0.005 for a in amounts_in(raw)))
    elif rtype in ("weight", "count"):
        v = amount(shown)
        nums = {float(n.replace(",", "")) for n in re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?", raw)}     # numbers as printed: '3 2683' is two numbers
        ok = v is not None and any(abs(n - v) < 1e-6 for n in nums)
        if not ok and rtype == "weight" and v is not None and any(abs(n - v * 1000) < 1e-3 for n in nums):
            return row("", f"{v * 1000:g} (on the document)", shown, "REVIEW",
                       "Nexus shows the document's weight divided by 1000 (kg printed, tonnes shown?): check the unit")
    elif rtype == "date":
        d, clean = find_date(shown)
        ok = d is not None and date_in(raw, d)
        if ok and not clean:
            return row("", "(date on the document)", shown, "FAIL", "the date is on the document but Nexus adds extra text to the value")
    elif rtype == "postal":
        ok = norm(shown) in nm
    else:
        ok = False
    return row("", "(found on the document)" if ok else None, shown, "PASS" if ok else "FAIL",
               "value found on the document" if ok else "this value is not on the document")


def words_found(shown: str, raw: str, need: float = 0.9) -> tuple[bool, str]:
    """Every word of the value Nexus shows must appear on the document. Compared without spaces or punctuation, because the
    PDF text often runs words together ('172PoonamalleeByPassRoad')."""
    nm = norm(raw)
    words = [norm(w) for w in re.split(r"[^A-Za-z0-9]+", shown) if norm(w)]
    if not words:
        return False, "no words"
    hit = sum(1 for w in words if w in nm)
    return hit / len(words) >= need, f"{hit}/{len(words)} words found on the document"


def table_row_values(raw: str) -> str:
    """Layouts that print a header row ('CustomerNumber OrderNumber PurchaseOrderNumber InvoiceNumber') and the values on the next row:
    returns 'Invoice Number: <value under that header>' lines, put in front of the text so the label search finds the right value."""
    lines, out = [ln.strip() for ln in raw.splitlines()], []
    for i, ln in enumerate(lines[:-1]):
        heads = re.findall(r"[A-Z][a-z]+(?:[A-Z][a-z]+)*", ln) if ln and " " in ln and ln.count(" ") >= 1 else []
        vals = lines[i + 1].split()
        if len(heads) >= 2 and len(heads) == len(vals) and all(re.fullmatch(r"[A-Za-z][A-Za-z]+", h) for h in ln.split()):
            for h, v in zip(ln.split(), vals):
                label = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", h)
                out.append(f"{label}: {v}")
    return "\n".join(out)


def compare_doc(kind: str, items: list[dict], raw: str) -> list[dict]:
    """Rows for every field of a Manifest / Invoice / Packing List panel, in panel order."""
    extra = table_row_values(raw)
    if extra:
        raw = extra + "\n" + raw
    rules, party_names, _ = SPECS[kind]
    rows, seen = [], {}
    for it in items:
        label, value = it["label"] or "(unlabelled)", it["value"] or ""
        if label in ("Name", "Address", "Postal Code"):
            n = seen[label] = seen.get(label, 0) + 1
            section = party_names[min(n - 1, len(party_names) - 1)]
            if label == "Postal Code":
                r = check_value("postal", None, value, raw)
            else:
                if value:
                    ok, note = words_found(value, raw)
                    r = row("", "(found on the document)" if ok else "(not found on the document)", value, "PASS" if ok else "FAIL", note)
                else:
                    r = row("", None, value, "INFO", "empty in Nexus")
        else:
            key = label if label in rules else ("Master Air Waybill" if kind == "MANIFEST" and label not in rules and not rows else label)
            section = {"PACKING": "Packing List", "DEBITNOTE": "Debit Note", "SHIPPERDOC": "Shipper Document"}.get(kind, kind.title())
            if key in rules:
                r = check_value(rules[key][0], rules[key][1], value, raw)
                label = key
            else:
                r = row("", None, value, "INFO", "shown by Nexus, no rule for this field" if value else "empty in Nexus")
        r.update(field=f"{section} · {label}", section=section, label=label)
        rows.append(r)
    return rows


# --- where the document's text comes from -----------------------------------------------------------------
def doc_text(cfg: Config, case: Case, kind: str) -> tuple[str, str] | None:
    """(text of the document's pages, 'file page n-m') for MANIFEST / INVOICE / PACKING in the case's sample PDF."""
    kw = cfg.settings["pdf_split"]["keywords"]
    sender = LocalSender.__new__(LocalSender)
    sender.cfg, sender.ld = cfg, cfg.settings["local_docs"]
    for f in [x for x in sample_files(cfg, case) if x.suffix.lower() == ".pdf"]:
        if case.mode == "individual":
            if sender.individual_type(f, case.sample_ref or case.id) != kind:
                continue
            pages = list(range(len(page_texts(f.read_bytes(), ocr=True))))
        else:
            want = {"SHIPPERDOC": ("SHIPPERDOC", "PO")}.get(kind, (kind,))
            if case.id.upper().startswith("SEA-"):          # Sea bills of lading are told apart by their layout (pdf_split_sea)
                from .pdf_split import detect_parts_sea, page_texts_layout
                texts = page_texts_layout(f.read_bytes(), ocr=True)
                parts = detect_parts_sea(texts, cfg.settings["pdf_split_sea"])
            else:
                texts = page_texts(f.read_bytes(), ocr=True)
                parts = detect_parts(texts, kw)
            pages = [i for part in parts if part.label in want for i in part.pages]   # incl. continuation pages
        if pages:
            data = f.read_bytes()
            with pdfplumber.open(str(f)) as pdf:
                got = [(pdf.pages[i].extract_text() or "") for i in pages]
            scanned = False
            for k, i in enumerate(pages):
                if len(got[k].strip()) < 25:                                  # a scanned page: OCR
                    from . import ocr as _ocr
                    got[k], scanned = _ocr.page_text(data, i), True
            where = f"{f.name} page {pages[0] + 1}" + (f"-{pages[-1] + 1}" if len(pages) > 1 else "") + (" (scan, OCR)" if scanned else "")
            return "\n".join(got), where
    return None


# --- the run ------------------------------------------------------------------------------------------------
def check_docs_one(cfg: Config, ui: UatPages, store: Store, case: Case, wait_seconds: float | None,
                   kinds: tuple[str, ...] | None = None) -> list[dict]:
    kinds = kinds or kinds_for(cfg, case)
    v = cfg.settings["validation"]
    out: list[dict] = []
    ref = store.ref_for_case(case.id)
    sent_at = store.last_sent_at(ref) if ref else None
    elapsed = (datetime.now() - sent_at).total_seconds() if sent_at else None
    sleep_s, wait = plan_wait(elapsed, v["initial_wait_seconds"], v["max_wait_seconds"], wait_seconds)
    _buffer(sleep_s, case.id)
    cell, info = ui.wait_for_case(f"{case.id} |", wait, v["poll_seconds"])
    base = {"case_id": case.id, "ipa": info.get("ipa", ""), "source": "", "verdict": "ERROR", "rows": [], "message": ""}
    if cell is None:
        return [dict(base, kind=k, message=f"no pre-alert for {case.id} in Nexus (checked the Pre-Alerts tab)") for k in kinds]
    ui.expand_row(cell)
    ui.open_viewer(cell, expanded=True)
    opts = ui.parent_options()
    evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    shown: dict[str, list[dict]] = {}
    for kind in kinds:
        res = dict(base, kind=kind)
        out.append(res)
        try:
            src = doc_text(cfg, case, kind)
            if not src:
                res["message"] = f"no {kind.lower()} pages found in the sample for {case.id}"
                continue
            raw, where = src
            res["source"] = where
            if kind == "MANIFEST":
                parent = next((o for o in opts if "Manifest" in o), None)
                if not parent:
                    res["message"] = "no Air Manifest parent in the viewer"
                    continue
                ui.select_parent(parent)
                ui.page.wait_for_timeout(1500)
            else:
                under = "Master" if kind == "DEBITNOTE" else "House"
                par = next((o for o in opts if o.startswith(under)), None)
                if not par:
                    res["message"] = f"no {under} parent in the viewer"
                    continue
                ui.select_parent(par)
                ui.page.wait_for_timeout(1500)
                pattern = PATTERNS[kind]
                if not open_document_page(ui.page, pattern):
                    res["message"] = f"{kind.lower()} expected under {under} but Nexus has none linked"
                    if kind == "PACKING":
                        res["verdict"] = "FAIL"
                    continue
            ui.screenshot(evidence / f"{kind.lower()}_data.png")
            items = read_panel_fields(ui.page)
            shown[kind] = items
            res["rows"] = compare_doc(kind, items, raw)
            if "(scan, OCR)" in where:                                       # OCR may misread: a difference is REVIEW, not FAIL
                from .master_check import ocr_adjust                              # a value Nexus shows is looked up in the OCR text first
                res["rows"] = ocr_adjust(res["rows"], raw)
                res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL"
            res["verdict"] = "FAIL" if any(r["result"] == "FAIL" for r in res["rows"]) else "PASS"
        except SessionExpired:
            raise
        except Exception as exc:
            res["message"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
    # cross-document consistency: the Packing List's Invoice No should be the Invoice's number
    inv = next((r for r in out if r["kind"] == "INVOICE"), None)
    pl = next((r for r in out if r["kind"] == "PACKING"), None)
    if inv and pl and inv["rows"] and pl["rows"]:
        inv_no = next((r["shown_in_nexus"] for r in inv["rows"] if r["label"] == "Invoice Number"), "")
        for r in pl["rows"]:
            if r["label"] == "Invoice No" and r["shown_in_nexus"] and inv_no and norm(r["shown_in_nexus"]) != norm(inv_no):
                r.update(result="REVIEW" if r["result"] == "PASS" else r["result"],
                         note=f"differs from the Invoice's number {inv_no} (the Packing List's own number appears here)")
    return out


def run_docs_check(cfg: Config, cases: list[Case], headless: bool = False, wait_seconds: float | None = None,
                   kinds: tuple[str, ...] | None = None) -> list[dict]:
    store = Store(cfg.state_dir / "agent.db")
    results: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case in cases:
                try:
                    results += check_docs_one(cfg, ui, store, case, wait_seconds, kinds or kinds_for(cfg, case))
                except SessionExpired:
                    raise
                except Exception as exc:
                    log.exception("document data check of %s failed", case.id)
                    results += [{"case_id": case.id, "kind": k, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                 "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"} for k in (kinds or ("MANIFEST", "INVOICE", "PACKING"))]
    except SessionExpired as exc:
        results.append({"case_id": "-", "kind": (kinds or ("MANIFEST",))[0], "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": str(exc)})
    except Exception as exc:
        results.append({"case_id": "-", "kind": (kinds or ("MANIFEST",))[0], "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                        "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    return results
