"""Sea data check: what Nexus shows for the Master / House record of a Sea shipment against the bill of lading in the source PDF.

The Air checks read an air-waybill layout; a Sea bill of lading is free-form and differs by carrier, so here every field Nexus shows is
looked up in the text of the document it came from (all pages of the MBL part for the Master, of the HBL part for the House).
PASS = the value is printed on the document, FAIL = it is not, REVIEW = partly, or the page is a scan read with OCR.
The document is the source of truth; values Nexus assigns itself (job number, branch, IDs...) are INFO."""
from __future__ import annotations

import logging
import re
from datetime import datetime

from .config import Config
from .master_check import MONTHS, _legal, attach_details as attach_master, norm, num, parse_date, row, tokens, verdict
from .house_check import attach_details as attach_house
from .nexus.session import SessionExpired
from .nexus.uat import UatPages, map_house_panel, map_master_panel, read_panel_inputs, read_party_ids
from .pdf_split import detect_parts_sea, page_texts_layout
from .store import Store
from .testsuite import Case, sample_files
from .validate import _buffer, plan_wait

log = logging.getLogger(__name__)

# Held by Nexus itself, or a label with nothing on the document to compare.
HELD_BY_NEXUS = {"Job Number", "Page Nos.", "Branch", "Job Type", "Status", "Shipper ID", "Consignee ID", "Party ID",
                 "Carrier Code", "Split Info", "Record Type"}
UNITS = {"KGS": {"K", "KG", "KGS", "KILOS"}, "KG": {"K", "KG", "KGS"}, "CBM": {"CBM", "M3"}, "PCS": {"PCS", "PC", "PKG", "PKGS"}}


def sea_source(cfg: Config, case: Case, kind: str) -> dict | None:
    """The first MBL / HBL part of the case's PDF: {pdf, pages (1-based), text, scanned}."""
    sea = cfg.settings["pdf_split_sea"]
    for f in [x for x in sample_files(cfg, case) if x.suffix.lower() == ".pdf"]:
        data = f.read_bytes()
        raw = page_texts_layout(data, ocr=False)
        scanned = {i for i, t in enumerate(raw) if len(t.strip()) < 25}
        texts = page_texts_layout(data, ocr=True) if scanned else raw
        part = next((p for p in detect_parts_sea(texts, sea) if p.label == kind), None)
        if part:
            return {"pdf": f, "pages": [i + 1 for i in part.pages], "text": "\n".join(texts[i] for i in part.pages),
                    "scanned": any(i in scanned for i in part.pages)}
    return None


def _numbers(text: str) -> set[float]:
    """Every number printed on the page, read both ways: 7,735.000 (comma = thousands) and 3800,00 (comma = decimals)."""
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        v = num(m.group(0))
        if v is not None:
            out.add(round(v, 4))
        if "," in m.group(0) and "." not in m.group(0):
            v = num(m.group(0).replace(",", "."))
            if v is not None:
                out.add(round(v, 4))
    return out


def _date_forms(d: tuple[int, int, int]) -> list[str]:
    day, month, year = d
    mon = list(MONTHS)[month - 1] if 1 <= month <= 12 and isinstance(MONTHS, dict) else ""
    return [f"{year}-{month:02d}-{day:02d}", f"{day:02d}/{month:02d}/{year}", f"{day}/{month}/{year}", f"{day:02d}.{month:02d}.{year}",
            f"{day:02d}-{mon}-{year}", f"{day:02d} {mon} {year}", f"{day:02d}-{mon}-{str(year)[2:]}", f"{day:02d}/{month:02d}/{str(year)[2:]}", f"{day}/{month}/{str(year)[2:]}", f"{day:02d}{mon}{year}"]


def check_value(label: str, value: str, text: str, nums: set[float]) -> tuple[str, str]:
    """(result, note) for one Nexus value against the document text."""
    flat, key = " ".join(text.upper().split()), norm(text)
    v = " ".join(str(value).split())
    if label == "Bill No." or label.lower().startswith("bill no"):
        return ("PASS", "printed on the document") if norm(v) in key else ("FAIL", "this bill number is not printed on the document")
    d = parse_date(v)
    if d:
        if any(norm(f) in key or f.upper() in flat for f in _date_forms(d)):
            return "PASS", "date printed on the document"
        return "FAIL", "this date is not printed on the document"
    n = num(v)
    if n is not None and re.fullmatch(r"[\d.,]+", v):
        return ("PASS", "number printed on the document") if round(n, 4) in nums else ("FAIL", "this number is not printed on the document")
    up = v.upper()
    if up in UNITS:
        return ("PASS", "unit printed on the document") if (tokens(text) & UNITS[up] or up in tokens(text)) else ("REVIEW", "unit not found as printed")
    e = _legal(v)
    toks = {t for t in tokens(e) if len(t) > 1}
    if not toks:
        return "INFO", "too short to compare"
    doc_toks = tokens(_legal(text))
    # a word also counts when the document prints it abbreviated (SPEDIZ. for SPEDIZIONI, INT for INTERNAZIONALI, SRL for SR)
    have = {t for t in toks if t in doc_toks or t in key or any(len(d) >= 3 and (t.startswith(d) or (len(t) >= 2 and d.startswith(t))) for d in doc_toks)}
    share = len(have) / len(toks)
    if share >= 0.9:
        return "PASS", "every word is on the document"
    if share >= 0.6:
        return "REVIEW", f"{len(have)}/{len(toks)} words are on the document"
    return "FAIL", f"only {len(have)}/{len(toks)} words are on the document (the party master / Nexus value may differ from the bill)"


def compare_sea(fields: dict, src: dict) -> list[dict]:
    text, nums = src["text"], _numbers(src["text"])
    rows = []
    for f in fields.get("fields", []):
        label, value, section = f["label"] or "(unlabelled field)", (f["value"] or "").strip(), f["section"]
        name = f"{section} · {label}"
        if not value:
            r = row(name, "", "", "INFO", "empty field, nothing to compare")
        elif section == "Cargo" and label == "Pieces" and not re.fullmatch(r"[\d.,]+", value):
            r = row(name, "", value, "INFO", "in the Sea panel this field holds the service type (FCL / LCL), not a piece count")
        elif label.startswith("Volume") and not re.search(r"\b(M3|CBM|MTQ|CUBIC|VOLUME|MEASUREMENT)\b", text, re.IGNORECASE):
            r = row(name, "", value, "REVIEW", "the document prints no volume, so this value cannot be confirmed")
        elif label in HELD_BY_NEXUS:
            r = row(name, "", value, "INFO", "assigned or held by Nexus; no document value")
        else:
            res, note = check_value(label, value, text, nums)
            if res == "FAIL" and src["scanned"]:
                res, note = "REVIEW", note + " (scanned page read with OCR)"
            r = row(name, "", value, res, note)
        r["section"], r["label"] = section, label
        rows.append(r)
    return rows


def check_sea_one(cfg: Config, ui: UatPages, store: Store, case: Case, kind: str, wait_seconds: float | None) -> dict:
    v = cfg.settings["validation"]
    title = "Master" if kind == "MBL" else "House"
    res = {"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": ""}
    src = sea_source(cfg, case, kind)
    if not src:
        res["message"] = f"no {kind} found in samples/{case.id}/"
        return res
    pg = src["pages"]
    res["source"] = f"{src['pdf'].name} page {pg[0]}" + (f"-{pg[-1]}" if len(pg) > 1 else "")
    ref = store.ref_for_case(case.id)
    sent_at = store.last_sent_at(ref) if ref else None
    elapsed = (datetime.now() - sent_at).total_seconds() if sent_at else None
    sleep_s, wait = plan_wait(elapsed, v["initial_wait_seconds"], v["max_wait_seconds"], wait_seconds)
    _buffer(sleep_s, case.id)
    cell, info = ui.wait_for_case(f"{case.id} |", wait, v["poll_seconds"])
    if cell is None:
        res["message"] = f"no pre-alert for {case.id} in Nexus (checked the Pre-Alerts tab)"
        return res
    res["ipa"] = info["ipa"]
    ui.expand_row(cell)
    rec = next((r for r in ui.read_shipment_details() if r.get("Record Type", "").startswith(title)), None)
    ui.open_viewer(cell, expanded=True)
    parent = next((o for o in ui.parent_options() if o.startswith(title)), None)
    if parent is None:
        res["message"] = f"no {title} parent in the viewer"
        return res
    ui.select_parent(parent)
    ui.page.wait_for_timeout(1500)
    ui.screenshot(cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id / f"{title.lower()}_data.png")
    items, ids = read_panel_inputs(ui.page), read_party_ids(ui.page)
    fields = (map_master_panel if kind == "MBL" else map_house_panel)(items, ids)
    (attach_master if kind == "MBL" else attach_house)(fields, rec)
    res["rows"] = compare_sea(fields, src)
    res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL" if src["scanned"] else ""
    if rec is None:
        res["message"] = f"the {title} row of the Shipment Details table was not found"
    res["verdict"] = verdict(res["rows"])
    return res


def run_sea_check(cfg: Config, cases: list[Case], kind: str, headless: bool = False, wait_seconds: float | None = None) -> list[dict]:
    from .nexus.session import NexusSession
    store = Store(cfg.state_dir / "agent.db")
    results: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case in cases:
                try:
                    results.append(check_sea_one(cfg, ui, store, case, kind, wait_seconds))
                except SessionExpired:
                    raise
                except Exception as exc:
                    log.exception("sea data check of %s failed", case.id)
                    results.append({"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                    "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    except SessionExpired as exc:
        results.append({"case_id": "-", "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": str(exc)})
    return results
