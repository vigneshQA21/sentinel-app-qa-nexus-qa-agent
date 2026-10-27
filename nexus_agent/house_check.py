"""House data check: what Nexus shows for the House record (Shipment Details row + data panel) against the House
air waybill page of the source PDF. The document is the source of truth."""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from .awb_extract import extract_master
from .config import Config
from .local_sender import LocalSender
from .master_check import _exact, _text, address_check, norm, num, parse_date, row, tokens, verdict
from .nexus.session import SessionExpired
from .nexus.uat import UatPages, map_house_panel, read_panel_inputs, read_party_ids
from .pdf_split import detect_parts, find_hawbs, page_labels, page_texts
from .store import Store
from .testsuite import Case, sample_files
from .validate import _buffer, plan_wait

log = logging.getLogger(__name__)
TABLE_ORDER = ["Job Number", "Page Nos.", "Bill No.", "Shipper", "Shipper ID", "Consignee", "Consignee ID", "Branch", "Job Type", "Status"]


def attach_details(fields: dict, rec: dict | None) -> dict:
    if rec is not None:
        fields["fields"] = [{"section": "Shipment Details", "label": k, "value": rec.get(k, ""), "readonly": True}
                            for k in TABLE_ORDER] + fields["fields"]
    return fields


def find_house_source(cfg: Config, case: Case) -> tuple[Path, int, str | None] | None:
    """(pdf, page index of the house AWB, house number read from the document)."""
    kw = cfg.settings["pdf_split"]["keywords"]
    sender = LocalSender.__new__(LocalSender)
    sender.cfg, sender.ld = cfg, cfg.settings["local_docs"]
    for f in [x for x in sample_files(cfg, case) if x.suffix.lower() == ".pdf"]:
        if case.mode == "individual" and sender.individual_type(f, case.sample_ref or case.id) != "HBL":
            continue
        texts = page_texts(f.read_bytes(), ocr=True)
        labels = page_labels(texts, kw)
        if "HBL" in labels:
            i = labels.index("HBL")
            hawbs = find_hawbs(texts, detect_parts(texts, kw), cfg)        # HBL pages are searched first
            return f, i, (hawbs[0] if hawbs else None)
    return None


def compare_house(doc: dict, house_no: str | None, master_doc: dict | None, ui: dict, details: dict | None,
                  rules: dict | None = None) -> list[dict]:
    """One row per field Nexus shows for the House, in panel order (table row first)."""
    rules = rules or {}
    checks: dict[tuple[str, str], dict] = {}
    page = doc.get("text") or ""

    def put(section, label, r):
        r["field"] = f"{section} · {label}"; r["section"], r["label"] = section, label
        checks[(section, label)] = r

    def info(section, label, exp, act, note):
        put(section, label, row("", exp, act, "INFO", note))

    shipper_text, consignee_text = " ".join(doc["shipper_lines"] or []), " ".join(doc["consignee_lines"] or [])

    if details is not None:                                              # Shipment Details table, House row
        sec = "Shipment Details"
        put(sec, "Bill No.", _exact("", house_no, details.get("Bill No.")))
        put(sec, "Shipper", _text("", shipper_text, details.get("Shipper"), "shipper found in the document block"))
        put(sec, "Consignee", _text("", consignee_text, details.get("Consignee"), "consignee found in the document block"))
        for who, key in (("Shipper", "shipper"), ("Consignee", "consignee")):
            pid, panel = details.get(f"{who} ID"), (ui.get(key) or {}).get("party_id")
            put(sec, f"{who} ID", row("", panel, pid, "PASS" if pid and panel and pid == panel else "FAIL" if pid and panel else "INFO",
                                      "same as the Party ID in the data panel" if pid and panel and pid == panel
                                      else "differs from the Party ID in the data panel" if pid and panel
                                      else "party-master ID, not printed on the document"))
        code = (doc["seg_to"] or [None])[-1]
        names = rules.get("airport_names", {}).get(code or "", [])
        r = _exact("", code, details.get("Branch"))
        if code and names:
            ok_city = bool(doc["destination_airport"]) and any(n in norm(doc["destination_airport"]) for n in map(norm, names))
            r["note"] = f"{code} = {names[0].title()}" + (", matches the document's destination" if ok_city else "")
        put(sec, "Branch", r)
        put(sec, "Job Type", _exact("", rules.get("expected_job_type", "New Job"), details.get("Job Type")))
        st = _exact("", rules.get("expected_house_status", "CW Sync Pending"), details.get("Status"))
        if st["result"] == "FAIL" and "pending" in (details.get("Status") or "").lower():
            st["note"] = "not the final status yet: Nexus is still processing this House"
        put(sec, "Status", st)
        info(sec, "Page Nos.", None, details.get("Page Nos."), "page of the house within its document group")
        info(sec, "Job Number", None, details.get("Job Number"), "assigned later when the job is created" if not details.get("Job Number") else "")

    put("House Air Waybill", "House Number (top right)", _exact("", house_no, ui.get("house_top")))
    put("House Air Waybill", "House Number (bottom right)", _exact("", house_no, ui.get("house_bottom")))
    put("House Air Waybill", "Master AWB Reference", _exact("", doc["awb_number"], ui.get("master_ref")))

    for who, lines in (("Shipper", doc["shipper_lines"]), ("Consignee", doc["consignee_lines"])):
        p, text = ui.get(who.lower(), {}), " ".join(lines or [])
        first = " ".join((p.get("name") or "").split()[:2])                # party-master names carry extra codes: "…ALPES FR01"
        r = _text("", text, p.get("name"), "name found in the document block")
        if r["result"] == "FAIL" and first and norm(first) in norm(text):
            extra = sorted(tokens(p.get("name")) - tokens(text))
            table_name = (details or {}).get(who)
            r.update(result="REVIEW", note="starts like the document's name but Nexus adds: " + ", ".join(extra)
                     + (f"; the Shipment Details table shows '{table_name}'" if table_name and norm(table_name) != norm(p.get("name")) else ""))
        r["expected_from_document"] = " ".join(lines[:2])                          # the name lines of the block (display only)
        put(who, "Name", r)
        a = address_check(text, p.get("address"))
        a["expected_from_document"] = " ".join(x for x in lines[2:] if not re.match(r"^(TE|TEL)\b", x))   # the address lines
        put(who, "Address", a)
        pc = p.get("postal_code")
        if not text:
            put(who, "Postal Code", row("", None, pc, "NOT_VERIFIABLE", "could not be read from the document"))
        elif not pc:
            put(who, "Postal Code", row("", "(see document block)", pc, "INFO", "empty in the party master"))
        else:
            ok = norm(pc) in norm(text)
            printed = ", ".join(dict.fromkeys(re.findall(r"\b\d{4,6}\b", text))) or "(in document block)"
            put(who, "Postal Code", row("", pc if ok else printed, pc, "PASS" if ok else "FAIL",
                                        "" if ok else "the party master's postal code is not the one printed on the document"))
        info(who, "Party ID", None, p.get("party_id"), "assigned by the Nexus party master, not printed on the document")

    mshipper = " ".join((master_doc or {}).get("shipper_lines") or [])
    if ui.get("agent_text") is not None:
        first = " ".join((mshipper.split())[:4])
        ok = bool(first) and norm(first) in norm(ui["agent_text"])
        put("Agent", "Agent / Origin Party (free text)", row("", first or None, ui["agent_text"], "PASS" if ok else "INFO",
                                                          "same party as the Master's shipper (origin agent)" if ok
                                                          else "not printed on the House page; no document value to compare"))

    pay = {"PP": "FREIGHT PREPAID", "PX": "FREIGHT PREPAID", "CC": "FREIGHT COLLECT", "CP": "FREIGHT COLLECT"}.get(doc["charges_code"] or "")
    put("Freight", "Freight Payment", _exact("", pay and f"{pay} (code {doc['charges_code']})", ui.get("freight_payment"),
                                             lambda a, b: norm(b) in norm(a)))
    put("Routing", "Airport Of Departure", _exact("", doc["departure_airport"], ui.get("departure_airport")))
    put("Routing", "Final Destination Airport", _exact("", doc["destination_airport"], ui.get("destination_airport")))

    segs = ui.get("segments", [])
    n_doc = len(doc["seg_to"] or [])
    put("Flight Route", "Type", _exact("", ("connecting" if n_doc > 1 else "direct") if n_doc else None, ui.get("route_type")))
    for i in range(max(n_doc, len(segs))):
        sec, s, has = f"Segment {i + 1}", (segs[i] if i < len(segs) else {}), i < n_doc
        put(sec, "From", _exact("", (doc["origin_code"] if i == 0 else doc["seg_to"][i - 1]) if has else None, s.get("from")))
        put(sec, "To", _exact("", doc["seg_to"][i] if has else None, s.get("to")))
        if i == 0 and doc["departure_airport"]:
            ok = norm(s.get("polname")) == norm(doc["departure_airport"])
            put(sec, "Polname", row("", doc["departure_airport"], s.get("polname"), "PASS" if ok else "INFO",
                                    "same as the airport of departure" if ok else "airport name differs from the document's departure airport"))
        elif i > 0 and i - 1 < len(segs):
            prev = segs[i - 1].get("podname")
            put(sec, "Polname", row("", prev, s.get("polname"), "PASS" if norm(prev) == norm(s.get("polname")) else "FAIL",
                                    "equals the previous segment's arrival airport (consistency)"))
        else:
            info(sec, "Polname", None, s.get("polname"), "airport name from the Nexus airport master")
        info(sec, "Polctry", None, s.get("polctry"), "country of the airport (Nexus airport master)")
        dest_doc = doc["destination_airport"] or ""
        if i == n_doc - 1 and dest_doc and s.get("podname"):
            ok = norm(s["podname"]) in norm(dest_doc)
            put(sec, "Podname", row("", dest_doc, s.get("podname"), "PASS" if ok else "INFO",
                                    "contained in the document's airport of destination" if ok else "airport name differs from the document's destination"))
        else:
            info(sec, "Podname", None, s.get("podname"), "airport name from the Nexus airport master")
        info(sec, "Podctry", None, s.get("podctry"), "country of the airport (Nexus airport master)")
        cn = s.get("carrier_name")
        seen = bool(cn) and norm(cn) in norm(page)
        put(sec, "Carrier Name", row("", "(printed on the document)" if seen else None, cn, "PASS" if seen else "INFO",
                                     "carrier name appears on the document" if seen else "not printed on the document (airline master data)"))
        cc = _exact("", doc["seg_carrier"][i] if has else None, s.get("carrier_code"), lambda a, b: norm(a) in norm(b))
        if cc["result"] == "FAIL" and s.get("carrier_code"):
            cc.update(result="INFO", note="Nexus airline-master code, not the IATA code printed on the document")
        put(sec, "Carrier Code", cc)
        fl = doc["flights"] or []
        put(sec, "Flight Number", _exact("", fl[i][0] if i < len(fl) else None, s.get("flight_number")))
        d = parse_date(s.get("flight_date"))
        put(sec, "Flight Date", row("", f"day {fl[i][1]}" if i < len(fl) else None, s.get("flight_date"),
                                    ("PASS" if d and d[0] == fl[i][1] else "FAIL") if i < len(fl) else "NOT_VERIFIABLE",
                                    "only the day is printed on the AWB" if i < len(fl) else "flight date not found in the document"))

    put("Cargo", "Pieces", _exact("", doc["pieces"], ui.get("pieces"), lambda a, b: num(a) == num(b)))
    info("Cargo", "Pieces Unit", None, ui.get("pieces_unit"), "unit not printed on the AWB (PCS is the Nexus default)")
    unit = {"K": "KGS", "L": "LBS"}.get(doc["gross_unit"] or "")
    put("Cargo", "Gross Weight", _exact("", doc["gross_weight"], ui.get("gross_weight"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Gross Weight Unit", _exact("", unit, ui.get("gross_unit")))
    put("Cargo", "Chargeable Weight", _exact("", doc["chargeable_weight"], ui.get("chargeable_weight"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Chargeable Weight Unit", _exact("", unit, ui.get("chargeable_unit")))
    put("Cargo", "Nature And Quantity Of Goods", _text("", doc["nature"], ui.get("nature")))
    vol = doc["volume"]
    put("Cargo", "Volume", _exact("", vol[0] if vol else None, ui.get("volume"), lambda a, b: num(a) == num(b)))
    put("Cargo", "Volume Unit", _exact("", {"M3": "CBM"}.get(vol[1], vol[1]) if vol else None, ui.get("volume_unit")))
    put("Reference", "Shippers Reference", _exact("", doc["reference"], ui.get("reference")))
    ex, ac = parse_date(doc["executed_on"]), parse_date(ui.get("executed_on"))
    put("Reference", "Executed On", row("", doc["executed_on"], ui.get("executed_on"), "NOT_VERIFIABLE" if not ex else "PASS" if ex == ac else "FAIL"))
    put("Reference", "Incoterm", _exact("", doc["incoterm"], ui.get("incoterm")))

    rows, used = [], set()
    for f in ui.get("fields", []):
        key = (f["section"], f["label"])
        if key in checks and key not in used:
            rows.append(checks[key]); used.add(key)
        else:
            r = row("", None, f["value"], "INFO", "empty field, no label" if not f["value"] else "shown by Nexus, no document value to compare")
            r.update(field=f"{f['section']} · {f['label']}", section=f["section"], label=f["label"])
            rows.append(r)
    for key, r in checks.items():
        if key not in used:
            r["note"] = (r["note"] + "; " if r["note"] else "") + "field not shown by Nexus"
            if r["result"] == "PASS":
                r["result"] = "FAIL"
            rows.append(r)
    return rows


def check_house_one(cfg: Config, ui: UatPages, store: Store, case: Case, wait_seconds: float | None) -> dict:
    from .master_check import find_master_source
    v = cfg.settings["validation"]
    res = {"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": ""}
    src = find_house_source(cfg, case)
    if not src:
        res["message"] = f"no house page found in samples/{case.id}/"
        return res
    res["source"] = f"{src[0].name} page {src[1] + 1}"
    doc = extract_master(src[0], src[1])
    msrc = find_master_source(cfg, case)
    mdoc = extract_master(msrc[0], msrc[1]) if msrc else None
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
    rec = next((r for r in ui.read_shipment_details() if r.get("Record Type", "").startswith("House")), None)
    ui.open_viewer(cell, expanded=True)
    house = next((o for o in ui.parent_options() if o.startswith("House")), None)
    if house is None:
        res["message"] = "no House parent in the viewer"
        return res
    ui.select_parent(house)
    ui.page.wait_for_timeout(1500)
    ui.screenshot(cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id / "house_data.png")
    fields = attach_details(map_house_panel(read_panel_inputs(ui.page), read_party_ids(ui.page)), rec)
    res["rows"] = compare_house(doc, src[2] or doc.get("house_number"), mdoc, fields, rec, v)
    if doc.get("ocr"):
        from .master_check import ocr_adjust
        res["rows"] = ocr_adjust(res["rows"], doc.get("text") or "")
        res["message"] = "scanned page: read with OCR, differences are REVIEW, not FAIL"
    res["verdict"] = verdict(res["rows"])
    if rec is None:
        res["message"] = "the House row of the Shipment Details table was not found"
    return res


def run_house_check(cfg: Config, cases: list[Case], headless: bool = False, wait_seconds: float | None = None) -> list[dict]:
    from .nexus.session import NexusSession
    store = Store(cfg.state_dir / "agent.db")
    results: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case in cases:
                try:
                    results.append(check_house_one(cfg, ui, store, case, wait_seconds))
                except SessionExpired:
                    raise
                except Exception as exc:                      # never crash: report it against the case and carry on
                    log.exception("house data check of %s failed", case.id)
                    results.append({"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                                    "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    except SessionExpired as exc:
        results.append({"case_id": "-", "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": str(exc)})
    except Exception as exc:
        results.append({"case_id": "-", "ipa": "", "source": "", "verdict": "ERROR", "rows": [],
                        "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    return results
