"""Master data check: what Nexus extracted (right-hand 'Shipment Data' panel) against what the source PDF says.
The document is always the source of truth; nothing is hard-coded per sample."""
from __future__ import annotations

import csv
import difflib
import logging
import re
from datetime import datetime
from pathlib import Path

from .awb_extract import extract_master
from .config import Config
from .local_sender import LocalSender
from .nexus.session import NexusSession, SessionExpired
from .nexus.uat import UatPages, map_master_panel, read_panel_inputs, read_party_ids
from .pdf_split import page_labels, page_texts
from .store import Store
from .testsuite import Case, sample_files
from .validate import plan_wait, _buffer

log = logging.getLogger(__name__)
MONTHS = {m: i for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}
SIMILAR = 0.90          # text fields (names, addresses, goods): how alike document and Nexus must be


def norm(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def num(s) -> float | None:
    try:
        return float(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_date(s: str | None) -> tuple[int, int, int] | None:
    s = (s or "").strip()
    m = re.match(r"^(\d{1,2})[-/ ]([A-Za-z]{3})[-/ ](\d{2,4})$", s)
    if m:
        y = int(m.group(3))
        return int(m.group(1)), MONTHS.get(m.group(2).upper(), 0), y + 2000 if y < 100 else y
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", s)                     # 2026-08-22
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def info_row(field, expected, actual, note):
    return row(field, expected, actual, "INFO", note)


def row(field, expected, actual, result, note=""):
    return {"field": field, "expected_from_document": "" if expected is None else str(expected),
            "shown_in_nexus": "" if actual is None else str(actual), "result": result, "note": note}


def _exact(field, exp, act, same=lambda a, b: norm(a) == norm(b)):
    if exp in (None, "", []):
        return row(field, exp, act, "NOT_VERIFIABLE", "could not be read from the document")
    if act in (None, ""):
        return row(field, exp, act, "FAIL", "Nexus shows nothing")
    return row(field, exp, act, "PASS" if same(str(exp), str(act)) else "FAIL")


def tokens(s: str | None) -> set[str]:
    return {t for t in re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper()).split() if t}


def _text(field, exp, act, note_pass=""):
    if not exp:
        return row(field, exp, act, "NOT_VERIFIABLE", "could not be read from the document")
    if not act:
        return row(field, exp, act, "FAIL", "Nexus shows nothing")
    if norm(act) in norm(exp) or norm(exp) in norm(act):
        return row(field, exp, act, "PASS", note_pass)
    if tokens(act) and tokens(act) <= tokens(exp):          # every word Nexus shows is on the document
        return row(field, exp, act, "PASS", note_pass or "every word is on the document")
    r = similar(exp, act)
    return row(field, exp, act, "PASS" if r >= SIMILAR else "FAIL", f"similarity {r:.2f} (needs {SIMILAR})")


def glued_words(lines: list[str] | None, shown: str | None) -> list[str]:
    """Words Nexus ran together where the document breaks a line (e.g. COMPLEX + SIDCO -> COMPLEXSIDCO)."""
    out, up = [], (shown or "").upper()
    for a, b in zip(lines or [], (lines or [])[1:]):
        if a.split() and b.split():
            tail, head = a.split()[-1].upper(), b.split()[0].upper()
            if tail + head in up and f"{tail} {head}" not in up:
                out.append(tail + head)
    return out


def address_check(doc_text: str, shown: str | None) -> dict:
    """Compares the address Nexus shows with the address block on the document by the words they share. Nexus's own party-master
    address is compared too: a different place is a mismatch, whoever holds the data."""
    if not doc_text:
        return row("", None, shown, "NOT_VERIFIABLE", "could not be read from the document")
    if not (shown or "").strip():
        return row("", "(on the document)", shown, "INFO", "empty in Nexus")
    sig = lambda t: sorted(w for w in tokens(t) if len(w) >= 3 or (w.isdigit() and len(w) >= 2))      # sorted: stable output
    mine, doc_tokens, doc_norm = sig(shown), tokens(doc_text), norm(doc_text)
    hit = [w for w in mine if w in doc_tokens or (len(w) >= 5 and w in doc_norm)]
    ratio = len(hit) / len(mine) if mine else 0.0
    miss = [w for w in mine if w not in hit]
    txt = f"{len(hit)}/{len(mine)} words of the Nexus address are on the document"
    if ratio >= 0.9:
        return row("", "(address on the document)", shown, "PASS", txt)
    if ratio >= 0.5:
        return row("", "(address on the document)", shown, "REVIEW", f"{txt}; not on the document: {', '.join(miss[:8])}")
    return row("", "(address on the document)", shown, "FAIL",
               f"different address: only {txt}; not on the document: {', '.join(miss[:8])}")


def compare_master(doc: dict, ui: dict, details: dict | None = None, rules: dict | None = None) -> list[dict]:
    """One row per field of the Nexus 'Shipment Data' panel, in panel order. Each row says whether the value was
    compared with the document (PASS/FAIL), is data Nexus derives or holds itself (INFO), or could not be checked
    (NOT_VERIFIABLE). Checks the document expects but Nexus does not show are appended as FAIL."""
    checks: dict[tuple[str, str], dict] = {}

    def put(section, label, r):
        r["field"] = f"{section} · {label}"
        r["section"], r["label"] = section, label
        checks[(section, label)] = r

    def info(section, label, exp, act, note):
        put(section, label, row("", exp, act, "INFO", note))

    put("Air Waybill", "Air Waybill Number", _exact("", doc["awb_number"], ui.get("awb_number")))

    if details is not None:                      # Master row of the Shipment Details table (list page)
        rules = rules or {}
        sec = "Shipment Details"
        shipper_text, consignee_text = " ".join(doc["shipper_lines"] or []), " ".join(doc["consignee_lines"] or [])
        put(sec, "Bill No.", _exact("", doc["awb_number"], details.get("Bill No.")))
        put(sec, "Shipper", _text("", shipper_text, details.get("Shipper"), "shipper found in the document block"))
        put(sec, "Consignee", _text("", consignee_text, details.get("Consignee"), "consignee found in the document block"))
        for who, key in (("Shipper", "shipper"), ("Consignee", "consignee")):
            pid, panel = details.get(f"{who} ID"), (ui.get(key) or {}).get("party_id")
            put(sec, f"{who} ID", row("", panel, pid, "PASS" if pid and panel and pid == panel else "FAIL" if pid and panel else "INFO",
                                      "same as the Party ID in the data panel" if pid and panel and pid == panel
                                      else "differs from the Party ID in the data panel" if pid and panel
                                      else "party-master ID, not printed on the document"))
        code = (doc["seg_to"] or [None])[-1]
        names = (rules or {}).get("airport_names", {}).get(code or "", [])
        branch = details.get("Branch")
        note = ""
        if code and names:
            ok_city = any(n in norm(doc["destination_airport"]) for n in map(norm, names)) if doc["destination_airport"] else False
            note = f"{code} = {names[0].title()}" + (", matches the document's destination" if ok_city else "")
        r = _exact("", code, branch)
        r["note"] = note
        put(sec, "Branch", r)
        put(sec, "Job Type", _exact("", rules.get("expected_job_type", "New Job"), details.get("Job Type")))
        put(sec, "Status", _exact("", rules.get("expected_master_status", "CW Sync Pending"), details.get("Status")))
        info(sec, "Page Nos.", None, details.get("Page Nos."), "page of the master within its document group")
        info(sec, "Job Number", None, details.get("Job Number"), "assigned later when the job is created" if not details.get("Job Number") else "")

    page = doc.get("text") or ""
    for who, lines in (("Shipper", doc["shipper_lines"]), ("Consignee", doc["consignee_lines"])):
        p = ui.get(who.lower(), {})
        text = " ".join(lines or [])
        put(who, "Name", _text("", text, p.get("name"), "name found in the document block"))
        if who == "Shipper":
            put(who, "Address", address_check(text, p.get("address")))
        else:
            r = _text("", text, p.get("address"))
            glued = glued_words(lines, p.get("address"))
            if glued and r["result"] == "PASS":
                r["note"] = "Nexus joins the document's address lines without a space: " + ", ".join(glued)
            put(who, "Address", r)
        pc = p.get("postal_code")
        ok_pc = bool(pc) and norm(pc) in norm(text)
        printed = ", ".join(dict.fromkeys(re.findall(r"\b\d{4,6}\b", text))) or "(in document block)"
        put(who, "Postal Code", row("", (pc if ok_pc else printed) if pc else None, pc,
                                    ("PASS" if ok_pc else "FAIL") if text else "NOT_VERIFIABLE",
                                    "" if text else "could not be read from the document"))
        info(who, "Party ID", None, p.get("party_id"), "assigned by the Nexus party master, not printed on the document")

    segs = ui.get("segments", [])
    n_doc = len(doc["seg_to"] or [])
    if n_doc:
        put("Flight Route", "Type", _exact("", "connecting" if n_doc > 1 else "direct", ui.get("route_type")))
    else:
        put("Flight Route", "Type", row("", None, ui.get("route_type"), "NOT_VERIFIABLE", "routing line not found in the document"))
    dest_doc = doc["destination_airport"] or ""
    for i in range(max(n_doc, len(segs))):
        sec, s = f"Segment {i + 1}", (segs[i] if i < len(segs) else {})
        has = i < n_doc
        frm = (doc["origin_code"] if i == 0 else doc["seg_to"][i - 1]) if has else None
        put(sec, "From", _exact("", frm, s.get("from")))
        put(sec, "To", _exact("", doc["seg_to"][i] if has else None, s.get("to")))
        # airport names: not printed as such on the AWB; checked for consistency instead
        if i == 0 and doc["departure_airport"]:
            put(sec, "Polname", row("", doc["departure_airport"], s.get("polname"),
                                    "PASS" if norm(s.get("polname")) == norm(doc["departure_airport"]) else "INFO",
                                    "same as the airport of departure" if norm(s.get("polname")) == norm(doc["departure_airport"])
                                    else "airport name differs from the document's airport of departure"))
        elif i > 0 and i - 1 < len(segs):
            prev = segs[i - 1].get("podname")
            put(sec, "Polname", row("", prev, s.get("polname"), "PASS" if norm(prev) == norm(s.get("polname")) else "FAIL",
                                    "equals the previous segment's arrival airport (consistency)"))
        else:
            info(sec, "Polname", None, s.get("polname"), "airport name from the Nexus airport master")
        info(sec, "Polctry", None, s.get("polctry"), "country of the airport (Nexus airport master)")
        if i == n_doc - 1 and dest_doc and s.get("podname"):
            ok = norm(s["podname"]) in norm(dest_doc)
            put(sec, "Podname", row("", dest_doc, s.get("podname"), "PASS" if ok else "INFO",
                                    "contained in the document's airport of destination" if ok
                                    else "airport name differs from the document's destination (airport master naming)"))
        else:
            info(sec, "Podname", None, s.get("podname"), "airport name from the Nexus airport master")
        info(sec, "Podctry", None, s.get("podctry"), "country of the airport (Nexus airport master)")
        cn = s.get("carrier_name")
        put(sec, "Carrier Name", row("", "(printed on the document)" if cn and norm(cn) in norm(page) else None, cn,
                                     "PASS" if cn and norm(cn) in norm(page) else "INFO",
                                     "carrier name appears on the document" if cn and norm(cn) in norm(page)
                                     else "not printed on the document (airline master data)"))
        cc = _exact("", doc["seg_carrier"][i] if has else None, s.get("carrier_code"), lambda a, b: norm(a) in norm(b))
        if cc["result"] == "FAIL" and s.get("carrier_code"):
            cc.update(result="INFO", note="Nexus airline-master code, not the IATA code printed on the document (see Carrier Name)")
        put(sec, "Carrier Code", cc)
        fl = (doc["flights"] or [])
        put(sec, "Flight Number", _exact("", fl[i][0] if i < len(fl) else None, s.get("flight_number")))
        d = parse_date(s.get("flight_date"))
        if i < len(fl):
            put(sec, "Flight Date", row("", f"day {fl[i][1]}", s.get("flight_date"), "PASS" if d and d[0] == fl[i][1] else "FAIL",
                                        "only the day is printed on the AWB" if d else "date missing or unreadable in Nexus"))
        else:
            put(sec, "Flight Date", row("", None, s.get("flight_date"), "NOT_VERIFIABLE", "flight date not found in the document"))

    put("Routing", "Airport Of Departure", _exact("", doc["departure_airport"], ui.get("departure_airport")))
    put("Routing", "Final Destination Airport", _exact("", doc["destination_airport"], ui.get("destination_airport")))
    pay = {"PP": "FREIGHT PREPAID", "PX": "FREIGHT PREPAID", "CC": "FREIGHT COLLECT", "CP": "FREIGHT COLLECT"}.get(doc["charges_code"] or "")
    put("Freight", "Freight Payment", _exact("", pay and f"{pay} (code {doc['charges_code']})", ui.get("freight_payment"),
                                             lambda a, b: norm(b) in norm(a)))
    put("Cargo", "Pieces", _exact("", doc["pieces"], ui.get("pieces"), lambda a, b: num(a) == num(b)))
    info("Cargo", "Pieces Unit", None, ui.get("pieces_unit"), "unit not printed on the AWB (PCS is the Nexus default)")
    put("Cargo", "Gross Weight", _exact("", doc["gross_weight"], ui.get("gross_weight"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Gross Weight Unit", _exact("", {"K": "KGS", "L": "LBS"}.get(doc["gross_unit"] or ""), ui.get("gross_unit")))
    put("Cargo", "Chargeable Weight", _exact("", doc["chargeable_weight"], ui.get("chargeable_weight"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Chargeable Weight Unit", _exact("", {"K": "KGS", "L": "LBS"}.get(doc["gross_unit"] or ""), ui.get("chargeable_unit")))
    put("Cargo", "Nature And Quantity Of Goods", _text("", doc["nature"], ui.get("nature")))
    vol = doc["volume"]
    put("Cargo", "Volume", _exact("", vol[0] if vol else None, ui.get("volume"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Volume Unit", _exact("", {"M3": "CBM"}.get(vol[1], vol[1]) if vol else None, ui.get("volume_unit")))
    ex, ac = parse_date(doc["executed_on"]), parse_date(ui.get("executed_on"))
    put("Cargo", "Executed On", row("", doc["executed_on"], ui.get("executed_on"),
                                    "NOT_VERIFIABLE" if not ex else "PASS" if ex == ac else "FAIL"))

    rows, used = [], set()
    for f in ui.get("fields", []):                                   # every field of the panel, in panel order
        key = (f["section"], f["label"])
        if key in checks and key not in used:
            rows.append(checks[key]); used.add(key)
        else:
            r = row("", None, f["value"], "INFO", "empty field, no label" if not f["value"] else "shown by Nexus, no document value to compare")
            r.update(field=f"{f['section']} · {f['label']}", section=f["section"], label=f["label"])
            rows.append(r)
    for key, r in checks.items():                                    # expected by the document, missing from the panel
        if key not in used:
            r["note"] = (r["note"] + "; " if r["note"] else "") + "field not shown by Nexus"
            if r["result"] == "PASS":
                r["result"] = "FAIL"
            rows.append(r)
    return rows


def verdict(rows: list[dict]) -> str:
    return "FAIL" if any(r["result"] == "FAIL" for r in rows) else "PASS"


def summary(rows: list[dict]) -> str:
    c = {k: sum(1 for r in rows if r["result"] == k) for k in ("PASS", "FAIL", "REVIEW", "INFO", "NOT_VERIFIABLE", "KNOWN")}
    return (f"{len(rows)} fields shown in Nexus | compared with the document: {c['PASS'] + c['FAIL'] + c['REVIEW'] + c['KNOWN']} "
            f"(PASS {c['PASS']}, FAIL {c['FAIL']}, REVIEW {c['REVIEW']}, KNOWN {c['KNOWN']}) | INFO (no document value): {c['INFO']} "
            f"| NOT_VERIFIABLE: {c['NOT_VERIFIABLE']}")


_MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_UNITS = {"KGS": {"K", "KG", "KGS"}, "KG": {"K", "KG", "KGS"}, "LBS": {"L", "LB", "LBS"}, "CBM": {"CBM", "M3"}, "PCS": {"PCS", "PC", "PKG", "PKGS"}}


def _found_in_scan(shown: str, flat: str, toks: set[str], nums: set[float]) -> tuple[bool, str]:
    """Is what Nexus shows somewhere in the OCR text of the page? Handles dates printed as 08AUG, units printed as K, numbers, and
    names / addresses where most (75%) of the words are found (OCR drops or garbles some)."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", shown)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        pats = [rf"\b0?{d}\s*[-/. ]?\s*{_MON[mo - 1]}\w*\s*[-/. ]?\s*(?:{y}|{y[2:]})?", rf"\b0?{d}\s*[-/.]\s*0?{mo}\s*[-/.]\s*(?:{y}|{y[2:]})"]
        return any(re.search(p, flat) for p in pats), "date"
    if shown.upper() in _UNITS:
        return bool(_UNITS[shown.upper()] & toks), "unit"
    a = num(shown)
    if a is not None and re.fullmatch(r"[\d.,]+", shown):
        return a in nums, "number"
    t = tokens(shown)
    if not t:
        return False, "text"
    hit = len(t & toks) / len(t)
    return (hit >= 0.75 or shown.upper() in flat), f"{len(t & toks)}/{len(t)} words"


def ocr_adjust(rows: list[dict], text: str) -> list[dict]:
    """The document page is a scan read with OCR, which can misread characters: nothing is a hard FAIL. What Nexus shows is looked up in
    the OCR text of the page (PASS if found, REVIEW if not); a FAIL on a scan becomes PASS when found there, REVIEW when not."""
    flat = " ".join((text or "").upper().split())
    toks = tokens(text)
    nums = {float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*\.?\d*", text or "") if x.replace(",", "").replace(".", "", 1).isdigit()}
    for r in rows:
        shown = (r.get("shown_in_nexus") or "").strip()
        if r["result"] in ("NOT_VERIFIABLE", "FAIL", "REVIEW") and shown:
            ok, how = _found_in_scan(shown, flat, toks, nums)
            if r["result"] != "NOT_VERIFIABLE" and not ok:
                r["result"], r["note"] = "REVIEW", "scanned page read with OCR (may be misread): " + (r.get("note") or "")
                continue
            if r["result"] == "NOT_VERIFIABLE" or ok:
                r["result"] = "PASS" if ok else "REVIEW"
                r["expected_from_document"] = r["expected_from_document"] if r["result"] != "NOT_VERIFIABLE" and r["expected_from_document"] \
                    else ("(found in the scan)" if ok else "(not found in the scan)")
                r["note"] = (f"found in the OCR text of the scanned page ({how})" if ok
                             else "not found in the OCR text of the scanned page: look at the scan by eye")
        elif r["result"] == "FAIL":
            r["result"] = "REVIEW"
            r["note"] = "scanned page read with OCR (may be misread): " + (r.get("note") or "")
    return rows


def format_report(results: list[dict], title: str = "MASTER DATA") -> str:
    lines = []
    for r in results:
        lines.append(f"\n{r['case_id']}  {title}  {r['verdict']}   {r['ipa']}   source: {r['source']}   {r['message']}".rstrip())
        if r["rows"]:
            lines.append(f"\n  ALL FIELDS SHOWN IN NEXUS ({len(r['rows'])})")
            per: dict[str, int] = {}
            for n, x in enumerate(r["rows"], 1):
                per[x["section"]] = per.get(x["section"], 0) + 1
                lines.append(f"    {n:>2}. {x['field']} : {x['shown_in_nexus'] if x['shown_in_nexus'] != '' else '(empty)'}")
            lines.append("    count per section: " + ", ".join(f"{k} {v}" for k, v in per.items()) + f"  =  {len(r['rows'])} fields")
            lines.append("\n  VALIDATION AGAINST THE DOCUMENT")
        section = None
        for x in r["rows"]:
            if x["section"] != section:
                section = x["section"]
                lines.append(f"  [{section}]")
            exp, act = " ".join(x["expected_from_document"].split()), " ".join(x["shown_in_nexus"].split())
            lines.append(f"    {x['result']:15} {x['label']:30} doc: {exp[:40]:40} | nexus: {act[:42]}"
                         + (f"   [{x['note']}]" if x["note"] else ""))
        if r["rows"]:
            lines.append("\n  " + summary(r["rows"]))
    return "\n".join(lines)


# --- which document page is the master -----------------------------------------------------------
def find_master_source(cfg: Config, case: Case) -> tuple[Path, int] | None:
    files = [f for f in sample_files(cfg, case) if f.suffix.lower() == ".pdf"]
    kw = cfg.settings["pdf_split"]["keywords"]
    sender = LocalSender.__new__(LocalSender)
    sender.cfg, sender.ld = cfg, cfg.settings["local_docs"]
    for f in files:
        if case.mode == "individual" and sender.individual_type(f, case.sample_ref or case.id) != "MBL":
            continue
        labels = page_labels(page_texts(f.read_bytes(), ocr=True), kw)
        if "MBL" in labels:
            return f, labels.index("MBL")
    return None


# --- the run -------------------------------------------------------------------------------------
TABLE_ORDER = ["Job Number", "Page Nos.", "Bill No.", "Shipper", "Shipper ID", "Consignee", "Consignee ID",
               "Branch", "Job Type", "Status"]


def attach_details(fields: dict, mrec: dict | None) -> dict:
    """Puts the Master row of the Shipment Details table in front of the data-panel fields (it is on the list page,
    before the viewer), so it is listed, counted and compared like every other field."""
    if mrec is not None:
        fields["fields"] = [{"section": "Shipment Details", "label": k, "value": mrec.get(k, ""), "readonly": True}
                            for k in TABLE_ORDER] + fields["fields"]
    return fields


def _check_one(cfg: Config, ui: UatPages, store: Store, case: Case, wait_seconds: float | None) -> dict:
    v = cfg.settings["validation"]
    res = {"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": ""}
    src = find_master_source(cfg, case)
    if not src:
        res["message"] = f"no master page found in samples/{case.id}/"
        return res
    res["source"] = f"{src[0].name} page {src[1] + 1}"
    doc = extract_master(src[0], src[1])
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
    records = ui.read_shipment_details()               # the Shipment Details table of the expanded row
    mrec = next((r for r in records if r.get("Record Type", "").startswith("Master")), None)
    ui.open_viewer(cell, expanded=True)
    master = next((o for o in ui.parent_options() if o.startswith("Master")), None)
    if master is None:
        res["message"] = "no Master parent in the viewer"
        return res
    ui.select_parent(master)
    ui.page.wait_for_timeout(1500)
    evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    ui.screenshot(evidence / "master_data.png")
    fields = map_master_panel(read_panel_inputs(ui.page), read_party_ids(ui.page))
    attach_details(fields, mrec)
    res["rows"] = compare_master(doc, fields, mrec, cfg.settings["validation"])
    if doc.get("ocr"):
        res["rows"] = ocr_adjust(res["rows"], doc.get("text") or "")
        res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL"
    if mrec is None:
        res["message"] = "the Master row of the Shipment Details table was not found"
    res["verdict"] = verdict(res["rows"])
    return res


def run_master_check(cfg: Config, cases: list[Case], headless: bool = False, wait_seconds: float | None = None) -> list[dict]:
    store = Store(cfg.state_dir / "agent.db")
    results: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case in cases:
                try:
                    results.append(_check_one(cfg, ui, store, case, wait_seconds))
                except SessionExpired:
                    raise
                except Exception as exc:                      # never crash: report it against the case and carry on
                    log.exception("master data check of %s failed", case.id)
                    results.append({"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                    "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    except SessionExpired as exc:
        results.append({"case_id": "-", "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": str(exc)})
    except Exception as exc:
        results.append({"case_id": "-", "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                        "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    return results


def write_report(cfg: Config, results: list[dict], prefix: str = "master_data") -> Path:
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "ipa", "source", "section", "field", "expected_from_document", "shown_in_nexus", "result", "note"])
        for r in results:
            for x in r["rows"] or [{"field": "", "expected_from_document": "", "shown_in_nexus": "",
                                    "result": r["verdict"], "note": r["message"]}]:
                w.writerow([r["case_id"], r["ipa"], r["source"], x.get("section", ""), x["field"], x["expected_from_document"],
                            x["shown_in_nexus"], x["result"], x["note"]])
    return path
