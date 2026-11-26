"""Field-by-field check of a multi-house job (MH-002..004): the Master and EVERY House parent of the job are each compared with their own
page of the source sample (MH-001's consolidated PDF). The single-house checkers read one PDF from samples/<case>/, which for the phased
cases holds only the last phase, so they would compare the wrong House with the wrong document. Read-only: sends and stores nothing."""
from __future__ import annotations

import logging
import re

from . import house_pick
from datetime import datetime

from .awb_extract import extract_master
from .config import Config
from .house_check import attach_details as attach_house, compare_house
from . import stdcompare as SC
from .master_check import attach_details as attach_master, compare_master, nexus_to_document as data_validation, ocr_adjust, verdict
from .mhphase import CASES, SOURCE_CASE, source_pdf, split
from .nexus.session import NexusSession
from .nexus.uat import UatPages, map_house_panel, map_master_panel, read_panel_inputs, read_party_ids

log = logging.getLogger(__name__)
KEY = lambda t: re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def source_pages(cfg: Config) -> tuple[object, int, dict[str, int]]:
    """(pdf path, master page index, {HAWB: 0-based first page that is not the repeated one})."""
    pdf = source_pdf(cfg)
    _, exp = split(pdf.read_bytes())
    dup = {p - 1 for pages in exp.duplicates.values() for p in pages}
    return pdf, 0, {h: min(p - 1 for p in pages if p - 1 not in dup) for h, pages in exp.pages.items()}


def write_csv(cfg: Config, results: list[dict]):
    import csv
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"mh_fields_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["record", "ipa", "source", "section", "field", "document_says", "nexus_shows", "class", "result", "note"])
        for r in results:
            from .docextract import fill_blanks
            for x in fill_blanks(r["rows"] or [{"field": "", "expected_from_document": "", "shown_in_nexus": "", "class": r["verdict"], "result": r["verdict"], "note": r["message"]}]):
                w.writerow([r["case_id"], r["ipa"], r["source"], x.get("section", ""), x["field"], x["expected_from_document"], x["shown_in_nexus"],
                            x.get("class", ""), x["result"], x["note"]])
    return path


def check_case(cfg: Config, ui: UatPages, case_id: str) -> list[dict]:
    v = cfg.settings["validation"]
    pdf, mpage, hpages = source_pages(cfg)
    mdoc = extract_master(pdf, mpage)
    cell, info = ui.wait_for_case(f"{case_id} |", 120, v["poll_seconds"])
    if cell is None:
        return [{"case_id": case_id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": "no pre-alert in Nexus"}]
    ui.expand_row(cell)
    records = ui.read_shipment_details()
    ui.open_viewer(cell, expanded=True)
    out: list[dict] = []
    day = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case_id
    for name in [o for o in ui.parent_options() if o.startswith(("Master", "House"))]:
        kind = "Master" if name.startswith("Master") else "House"
        m = re.search(r"\((.*)\)", name)
        bill = m.group(1) if m else ""                                    # 'House 1': a House without a bill number
        rec = next((r for r in records if r.get("Record Type", "").startswith(kind) and KEY(r.get("Bill No.")) == KEY(bill)), None)
        res = {"case_id": f"{case_id} · {name}", "ipa": info["ipa"], "source": "", "verdict": "ERROR", "rows": [], "message": ""}
        try:
            ui.select_parent(name)
            ui.page.wait_for_timeout(1500)
            ui.screenshot(day / f"fields_{KEY(name)}.png")
            if kind == "Master":
                res["source"] = f"{pdf.name} page {mpage + 1}"
                fields = attach_master(map_master_panel(read_panel_inputs(ui.page), read_party_ids(ui.page)), rec)
                res["rows"] = data_validation(compare_master(mdoc, fields, rec, v), "" if mdoc.get("ocr") else mdoc.get("text") or "")
                if mdoc.get("ocr"):                                   # scanned page: what Nexus shows is looked up in the OCR text
                    res["rows"] = ocr_adjust(res["rows"], mdoc.get("text") or "")
                    for x in res["rows"]:
                        x["class"] = SC.classify(x)
                    res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL"
            else:
                page = next((p for h, p in hpages.items() if KEY(h) == KEY(bill)), None)
                if page is None:                                          # Nexus made a House the sample does not have: a finding
                    res["rows"] = house_pick.extra_rows([rec or {"Bill No.": bill}], "House", list(hpages))
                    res["verdict"] = "FAIL"
                    res["message"] = f"{bill or name} is not a House of the source sample (additional House)"
                    out.append(res)
                    continue
                res["source"] = f"{pdf.name} page {page + 1}"
                fields = attach_house(map_house_panel(read_panel_inputs(ui.page), read_party_ids(ui.page)), rec)
                hdoc = extract_master(pdf, page)
                res["rows"] = data_validation(compare_house(hdoc, bill, mdoc, fields, rec, v), "" if hdoc.get("ocr") else hdoc.get("text") or "")
                if hdoc.get("ocr"):
                    res["rows"] = ocr_adjust(res["rows"], hdoc.get("text") or "")
                    for x in res["rows"]:
                        x["class"] = SC.classify(x)
                    res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL"
            res["verdict"] = verdict(res["rows"])
            if rec is None:
                res["message"] = (res["message"] + "; " if res["message"] else "") + "its row of the Shipment Details table was not found"
        except Exception as exc:
            res["message"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
        out.append(res)
    return out


def run_mh_fields(cfg: Config, case_ids: list[str], headless: bool = False) -> list[dict]:
    results: list[dict] = []
    with NexusSession(cfg, headless=headless) as sess:
        sess.ensure_logged_in()
        ui = UatPages(sess.page, cfg)
        for cid in case_ids:
            if cid not in CASES and cid != SOURCE_CASE:
                results.append({"case_id": cid, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": "not a multi-house case"})
                continue
            results += check_case(cfg, ui, cid)
    return results


def triage_text(results: list[dict]) -> str:
    """PASS / FAIL / DISCUSSION NEEDED per record, same buckets as the run report (no earlier run of these records is stored, so nothing is a regression yet)."""
    out = ["DATA VALIDATION RESULT  (Nexus field -> document; nothing below is a bug until you confirm it)"]
    for r in results:
        b: dict[str, list] = {SC.PASS_B: [], SC.DISCUSS_B: [], SC.FAIL_B: [], SC.INFO_B: [], SC.KNOWN_B: []}
        for x in r["rows"]:
            b[SC.triage(x.get("class") or SC.classify(x))].append(x)
        out.append(f"  {r['case_id']}:  PASS {len(b[SC.PASS_B])}   FAIL {len(b[SC.FAIL_B])}   DISCUSSION NEEDED {len(b[SC.DISCUSS_B])}   (info {len(b[SC.INFO_B])})")
        for x in b[SC.FAIL_B] + b[SC.DISCUSS_B]:
            out.append(f"      [{x.get('class')}] {x['field']}: document says '{(x['expected_from_document'] or '-')[:60]}' | Nexus shows '{(x['shown_in_nexus'] or '-')[:60]}'")
    return "\n".join(out)
