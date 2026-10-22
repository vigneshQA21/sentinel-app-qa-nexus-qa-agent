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
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def row(field, expected, actual, result, note=""):
    return {"field": field, "expected_from_document": "" if expected is None else str(expected),
            "shown_in_nexus": "" if actual is None else str(actual), "result": result, "note": note}


def _exact(field, exp, act, same=lambda a, b: norm(a) == norm(b)):
    if exp in (None, "", []):
        return row(field, exp, act, "NOT_VERIFIABLE", "could not be read from the document")
    if act in (None, ""):
        return row(field, exp, act, "FAIL", "Nexus shows nothing")
    return row(field, exp, act, "PASS" if same(str(exp), str(act)) else "FAIL")


def _text(field, exp, act, note_pass=""):
    if not exp:
        return row(field, exp, act, "NOT_VERIFIABLE", "could not be read from the document")
    if not act:
        return row(field, exp, act, "FAIL", "Nexus shows nothing")
    if norm(act) in norm(exp) or norm(exp) in norm(act):
        return row(field, exp, act, "PASS", note_pass)
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


def compare_master(doc: dict, ui: dict) -> list[dict]:
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

    page = doc.get("text") or ""
    for who, lines in (("Shipper", doc["shipper_lines"]), ("Consignee", doc["consignee_lines"])):
        p = ui.get(who.lower(), {})
        text = " ".join(lines or [])
        put(who, "Name", _text("", text, p.get("name"), "name found in the document block"))
        if who == "Shipper":
            info(who, "Address", text, p.get("address"), "party-master data (read-only in Nexus), not compared with the document")
        else:
            r = _text("", text, p.get("address"))
            glued = glued_words(lines, p.get("address"))
            if glued and r["result"] == "PASS":
                r["note"] = "Nexus joins the document's address lines without a space: " + ", ".join(glued)
            put(who, "Address", r)
        pc = p.get("postal_code")
        put(who, "Postal Code", row("", pc and "(in document block)", pc,
                                    ("PASS" if pc and norm(pc) in norm(text) else "FAIL") if text else "NOT_VERIFIABLE",
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
        put(sec, "Carrier Code", _exact("", doc["seg_carrier"][i] if has else None, s.get("carrier_code"),
                                        lambda a, b: norm(a) in norm(b)))
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
    c = {k: sum(1 for r in rows if r["result"] == k) for k in ("PASS", "FAIL", "INFO", "NOT_VERIFIABLE")}
    return (f"{len(rows)} fields in the Nexus Master panel | compared with the document: {c['PASS'] + c['FAIL']} "
            f"(PASS {c['PASS']}, FAIL {c['FAIL']}) | INFO (no document value): {c['INFO']} | NOT_VERIFIABLE: {c['NOT_VERIFIABLE']}")


def format_report(results: list[dict]) -> str:
    lines = []
    for r in results:
        lines.append(f"\n{r['case_id']}  MASTER DATA  {r['verdict']}   {r['ipa']}   source: {r['source']}   {r['message']}".rstrip())
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
            lines.append(f"    {x['result']:15} {x['label']:30} doc: {x['expected_from_document'][:40]:40} | nexus: {x['shown_in_nexus'][:42]}"
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
        labels = page_labels(page_texts(f.read_bytes()), kw)
        if "MBL" in labels:
            return f, labels.index("MBL")
    return None


# --- the run -------------------------------------------------------------------------------------
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
    ui.open_viewer(cell)
    master = next((o for o in ui.parent_options() if o.startswith("Master")), None)
    if master is None:
        res["message"] = "no Master parent in the viewer"
        return res
    ui.select_parent(master)
    ui.page.wait_for_timeout(1500)
    evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    ui.screenshot(evidence / "master_data.png")
    fields = map_master_panel(read_panel_inputs(ui.page), read_party_ids(ui.page))
    res["rows"] = compare_master(doc, fields)
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


def write_report(cfg: Config, results: list[dict]) -> Path:
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"master_data_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["case_id", "ipa", "source", "section", "field", "expected_from_document", "shown_in_nexus", "result", "note"])
        for r in results:
            for x in r["rows"] or [{"field": "", "expected_from_document": "", "shown_in_nexus": "",
                                    "result": r["verdict"], "note": r["message"]}]:
                w.writerow([r["case_id"], r["ipa"], r["source"], x.get("section", ""), x["field"], x["expected_from_document"],
                            x["shown_in_nexus"], x["result"], x["note"]])
    return path
