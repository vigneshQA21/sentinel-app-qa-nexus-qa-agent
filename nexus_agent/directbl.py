"""Air Direct BL (DBL-nnn cases): a Master with no House document. Nexus must create the House from the Master (requirement "Direct BL Shipment
Requirement (Only for Air MOT)", points 1 to 9 and the XML changes). The check reads the pre-alert in the UI and reports PASS / FAIL / REVIEW /
NOT_RUN for every point of the requirement.

`evaluate` is pure (the page data it needs is passed in), so it is tested without Nexus. Results use the same row layout as the other data checks
({section, field, expected_from_document, shown_in_nexus, result, note}), so master_check.write_report writes the CSV.
What is NOT checked here and says so: the points that need an edit or a push in Nexus (consignee / shipper dropdown change, Master-to-House
synchronization, XML). The agent never edits or pushes."""
from __future__ import annotations

import logging
import re

from . import house_pick
from datetime import datetime
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

MAWB_FORMAT = re.compile(r"^\d{3}[- ]?\d{4}[- ]?\d{4}$|^\d{3}[- ]?\d{8}$")        # 123-12345678, 123 1234 5678, 123-1234 5678, 12312345678
# India's Direct BL rules (the requirement this check was written for). Every tenant sets its own in settings.yaml `direct_bl:`;
# these defaults are used ONLY for India, so another tenant never silently inherits India's destination or consignee rules.
INDIA_RULES = {"destination_country": "IN", "destination_name": "India", "destination_expected": "India (DELHI on the document)",
               "excluded_consignees": ["FLYJAC", "LOGISTEED"]}
EXCLUDED_CONSIGNEES = tuple(INDIA_RULES["excluded_consignees"])                         # kept for existing imports


def rules_for(cfg: Config) -> dict | None:
    """The tenant's Direct BL rules: settings `direct_bl:` over India's defaults for India; None for a tenant that has not set any."""
    own = cfg.settings.get("direct_bl")
    if own:
        return {**INDIA_RULES, **own} if cfg.tenant == "india" else dict(own)
    return dict(INDIA_RULES) if cfg.tenant == "india" else None
SKIP_LABELS = ("Party ID", "(unlabelled")                                             # compared on the Shipment Details rows / not a Master value

POINTS = {
    "1": "1. Direct BL identification (MAWB 11 digits, India destination, consignee not FLYJAC/LOGISTEED)",
    "2": "2. House record creation from the Master (Master No. -> House No., Shipper, other details)",
    "3": "3. Consignee handling (House and Master Consignee correspond)",
    "4": "4. Shipper handling (House and Master Shipper correspond)",
    "6": "6. Branch determined from the Destination Airport",
    "8": "8. House document: field and action access",
    "9": "9. House document preview",
    "X": "XML changes (DRT shipment type, no Receiving / Sending Agent)",
}


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _row(point: str, field: str, expected: str, shown: str, result: str, note: str = "") -> dict:
    return {"section": POINTS[point], "field": field, "expected_from_document": expected, "shown_in_nexus": shown, "result": result, "note": note}


def _key(f: dict) -> tuple[str, str]:
    return f["section"], f["label"]


def _bar_state(bar: list[dict], *needles: str) -> dict | None:
    """The toolbar button whose text or tooltip starts with one of the needles (case-insensitive)."""
    for b in bar:
        label = f"{b.get('text', '')} {b.get('title', '')}".strip().lower()
        if any(label.startswith(n.lower()) or n.lower() in (b.get("title", "") or "").lower() for n in needles):
            return b
    return None


def _off(b: dict) -> bool:
    return bool(b.get("disabled") or b.get("ariaDisabled") == "true" or b.get("op", "1") != "1")


def _point1_title(rules: dict | None) -> str:
    """India's title is the original text, so its reports and the Golden comparison keep the same section name."""
    if rules is None:
        return "1. Direct BL identification (MAWB 11 digits; no destination / consignee rules configured for this tenant)"
    cons = "/".join(rules.get("excluded_consignees") or []) or "none excluded"
    return f"1. Direct BL identification (MAWB 11 digits, {rules.get('destination_name') or rules.get('destination_country')} destination, consignee not {cons})"


def evaluate(case_sample_ref: str, parents: list[str], records: list[dict], master_fields: list[dict], house_fields: list[dict],
             house_inputs: list[dict], row_controls: list[dict], bar_house: list[dict], bar_master: list[dict],
             rules: dict | None = INDIA_RULES) -> list[dict]:
    """`rules` = the tenant's Direct BL rules (see rules_for); None = not configured: those identification points are NOT_RUN."""
    rows: list[dict] = []
    title1 = _point1_title(rules)
    _row1 = lambda *a, **k: {**_row("1", *a, **k), "section": title1}
    m_rec = next((r for r in records if r.get("Record Type", "").startswith("Master")), {})
    h_recs = [r for r in records if r.get("Record Type", "").startswith("House")]
    h_rec = house_pick.choose(records, "House")[0] or {}                  # a House with a real bill, not an extra empty one
    m = {_key(f): f["value"] for f in master_fields}
    h = {_key(f): f["value"] for f in house_fields}
    mawb = m.get(("Air Waybill", "Air Waybill Number"), "") or m_rec.get("Bill No.", "")

    # 1 identification ----------------------------------------------------------------------------------------------------------------
    ok = bool(MAWB_FORMAT.match((mawb or "").strip()))
    same = not case_sample_ref or _norm(case_sample_ref) == _norm(mawb)
    rows.append(_row1("MAWB format (11 digits)", f"{case_sample_ref} (11-digit format)", mawb, "PASS" if ok and same else "FAIL",
                      "" if ok and same else ("MAWB is not an 11-digit number" if not ok else "MAWB differs from the sample's number")))
    dest = m.get(("Segment 1", "Podctry"), "")
    cons = m.get(("Consignee", "Name"), "")
    shown_dest = f"{m.get(('Routing', 'Final Destination Airport'), '')} ({dest})"
    if rules is None:
        why = "no Direct BL rules in this tenant's settings.yaml (direct_bl:); nothing is assumed from another tenant"
        rows.append(_row1("Destination country", "(not configured)", shown_dest, "NOT_RUN", why))
        rows.append(_row1("Consignee not excluded", "(not configured)", cons, "NOT_RUN", why))
    else:
        want, name = str(rules.get("destination_country") or "").upper(), rules.get("destination_name") or rules.get("destination_country")
        rows.append(_row1(f"Destination is {name}", rules.get("destination_expected") or name, shown_dest,
                          "PASS" if dest.upper() == want else "FAIL", "" if dest.upper() == want else f"destination country is not {want}"))
        excluded = [str(x) for x in rules.get("excluded_consignees") or []]
        bad = [x for x in excluded if x.upper() in cons.upper()]
        label = " / ".join(excluded) or "an excluded consignee"
        rows.append(_row1(f"Consignee is not {label}", f"not {label}", cons, "FAIL" if bad else "PASS",
                          "this consignee follows the existing flow, not Direct BL" if bad else ""))
    houses = [p for p in parents if p.startswith("House")]
    status = h_rec.get("Status", "")
    one = len(houses) == 1 and _norm(mawb) in _norm(houses[0])
    rows.append(_row1("Identified as Direct BL: exactly one House, named after the Master", "1 House parent, number = Master number",
                     f"{len(houses)} House parent(s): {', '.join(houses) or 'none'}; status '{status}'", "PASS" if one and "DIRECT BL" in status.upper() else "FAIL",
                     "" if one and "DIRECT BL" in status.upper() else "Nexus did not create exactly one House marked Direct BL"))

    # 2 house creation ----------------------------------------------------------------------------------------------------------------
    nums = {"House Number (top right)": h.get(("House Air Waybill", "House Number (top right)"), ""),
            "House Number (bottom right)": h.get(("House Air Waybill", "House Number (bottom right)"), ""),
            "House row Bill No.": h_rec.get("Bill No.", "")}
    for label, v in nums.items():
        rows.append(_row("2", f"Master No. -> {label}", mawb, v, "PASS" if _norm(v) == _norm(mawb) and v else "FAIL", "" if _norm(v) == _norm(mawb) and v else "House number differs from the Master number"))
    for lab in ("Name", "Address", "Postal Code"):
        a, b = m.get(("Shipper", lab), ""), h.get(("Shipper", lab), "")
        rows.append(_row("2", f"Master Shipper -> House Shipper · {lab}", a or "(blank on the Master)", b or "(blank)", "PASS" if a == b else "FAIL", "" if a == b else "House value differs from the Master"))
    compared = skipped = 0
    for (sec, lab), val in m.items():
        if sec in ("Air Waybill", "Shipper", "Consignee") or any(lab.startswith(s) for s in SKIP_LABELS):
            continue
        hv, where = h.get((sec, lab)), sec
        if hv is None:                                          # the House panel files some fields under another heading (Executed On: Cargo / Reference)
            same_label = [(k, v) for k, v in h.items() if k[1] == lab]
            if len(same_label) == 1:
                (where, _), hv = same_label[0]
        if hv is None:
            skipped += 1
            rows.append(_row("2", f"Other Master detail · {sec} · {lab}", val, "(field not in the House panel)", "REVIEW", "the House panel has no field of this name"))
            continue
        compared += 1
        rows.append(_row("2", f"Other Master detail · {sec} · {lab}", val or "(blank)", hv or "(blank)", "PASS" if val == hv else "FAIL",
                         ("" if val == hv else "House value differs from the Master") + (f" (House lists it under '{where}')" if where != sec else "")))

    # 3 / 4 consignee and shipper -----------------------------------------------------------------------------------------------------
    for pt, who, idcol in (("3", "Consignee", "Consignee ID"), ("4", "Shipper", "Shipper ID")):
        for lab in ("Name", "Address", "Postal Code"):
            a, b = m.get((who, lab), ""), h.get((who, lab), "")
            rows.append(_row(pt, f"House {who} = Master {who} · {lab}", a or "(blank on the Master)", b or "(blank)", "PASS" if a == b else "FAIL", "" if a == b else "differs"))
        a, b = m_rec.get(idcol, ""), h_rec.get(idcol, "")
        rows.append(_row(pt, f"{idcol} (Shipment Details rows)", a, b, "PASS" if a and a == b else "FAIL", "" if a and a == b else f"{idcol} differs or is blank"))
        # the dropdown-change half of points 3 and 4 is EXCLUDED for now (user, 18-Nov-2026): needs an edit on an un-pushed Direct BL job

    # 5 documents ---------------------------------------------------------------------------------------------------------------------
    # point 5 (document mapping to the auto-created House) is EXCLUDED for now (user, 18-Nov-2026): no sample with Invoice / Packing List.

    # 6 branch ------------------------------------------------------------------------------------------------------------------------
    mb, hb = m_rec.get("Branch", ""), h_rec.get("Branch", "")
    to_code = m.get(("Segment 1", "To"), "")
    if not hb or mb != hb:
        rows.append(_row("6", "Branch on the House and the Master", "same, not blank", f"Master '{mb}', House '{hb}'", "FAIL", "branch is blank or differs"))
    else:
        rows.append(_row("6", "Branch from the Destination Airport", f"branch of destination {to_code}", hb, "PASS" if _norm(hb) == _norm(to_code) else "REVIEW",
                         "" if _norm(hb) == _norm(to_code) else "branch differs from the airport code: there is no airport-to-branch table to decide"))

    # 7 sync --------------------------------------------------------------------------------------------------------------------------
    # point 7 (a Master edit reaches the House) is EXCLUDED for now (user, 18-Nov-2026): needs an edit on an un-pushed Direct BL job.

    # 8 access ------------------------------------------------------------------------------------------------------------------------
    open_inputs = [i for i in house_inputs if not i.get("readonly")]
    rows.append(_row("8", "House fields are disabled (viewer panel)", "all fields read-only", f"{len(house_inputs) - len(open_inputs)} of {len(house_inputs)} read-only",
                     "PASS" if house_inputs and not open_inputs else "FAIL", "" if house_inputs and not open_inputs else f"{len(open_inputs)} field(s) can be edited"))
    hrow = next((r for r in row_controls if r["text"].startswith("House")), {"controls": []})
    ctl = {c["label"]: c for c in hrow["controls"]}

    def _find(*parts: str):
        return next((c for k, c in ctl.items() if any(p.lower() in k.lower() for p in parts)), None)

    editable = [c["label"] for c in hrow["controls"] if not _off(c) and c["label"] not in ("View documents",) and not c["label"].lower().startswith(("push", "approve", "job number"))]
    rows.append(_row("8", "Only Job Number and Job Type are editable (Shipment Details row)", "Job Number / Job Type only", ", ".join(editable) or "no other control",
                     "PASS" if not editable else "FAIL", "" if not editable else "other controls are enabled on the House row"))
    for name, parts in (("View", ("view",)), ("Push", ("push",)), ("Approve", ("approve",))):
        c = _find(*parts)
        res = "FAIL" if c is None or _off(c) else "PASS"
        shown = "not on the row" if c is None else ("disabled" if _off(c) else "enabled")
        note = "" if res == "PASS" else ("the House's Approve leg is disabled while the Master's is enabled: it may wait for the Master to be approved first, the requirement says it stays enabled"
                                          if name == "Approve" else "")
        rows.append(_row("8", f"{name} action on the House row", "enabled", shown, res, note))
    rows.append(_row("8", "Job Type dropdown", "enabled", f"shown as text '{h_rec.get('Job Type', '')}', no control on the row (the Master row is the same)", "REVIEW",
                     "cannot tell whether the Job Type can be changed without editing: check by eye"))

    # 9 preview -----------------------------------------------------------------------------------------------------------------------
    rows.append(_row("9", "Extracted data section is disabled", "disabled", f"{len(house_inputs) - len(open_inputs)} of {len(house_inputs)} fields read-only",
                     "PASS" if house_inputs and not open_inputs else "FAIL", ""))
    rows.append(_row("9", "Standard House field names with the Master's data", "House field names, Master values", f"{compared} fields compared with the Master",
                     "PASS" if compared and not any(r["result"] == "FAIL" and r["field"].startswith("Other Master detail") for r in rows) else "FAIL", ""))
    hitl_h, hitl_m = _bar_state(bar_house, "verify", "open the hitl"), _bar_state(bar_master, "verify", "open the hitl")
    rows.append(_row("9", "Verify (HITL) is disabled", "disabled", "not offered on the House" if hitl_h is None else ("disabled" if _off(hitl_h) else "enabled"),
                     "PASS" if hitl_h is None or _off(hitl_h) else "FAIL",
                     f"the Master toolbar has it ({'enabled' if hitl_m and not _off(hitl_m) else 'n/a'}), the House toolbar does not" if hitl_h is None else ""))
    rc = _bar_state(bar_house, "re-classify", "select at least one page")
    rows.append(_row("9", "Re-classify is disabled", "disabled", "not on the toolbar" if rc is None else ("disabled" if _off(rc) else "enabled"),
                     "FAIL" if rc is not None and not _off(rc) else "REVIEW",
                     "disabled, but its tooltip is 'select at least one page' (the same reason as on the Master): not proof that Direct BL disables it" if rc is not None and _off(rc) else ""))
    sv = _bar_state(bar_house, "save", "direct-bl house is a read-only")
    rows.append(_row("9", "Save is disabled", "disabled", "not on the toolbar" if sv is None else ("disabled" if _off(sv) else "enabled"),
                     "PASS" if sv is not None and _off(sv) else "FAIL", (sv or {}).get("title", "") if sv is not None else "no Save button found"))
    for name, parts in (("Push", ("submit",)), ("Approve", ("approve",))):
        b = _bar_state(bar_house, *parts)
        res = "PASS" if b is not None and not _off(b) else "FAIL"
        rows.append(_row("9", f"{name} stays enabled in the preview", "enabled", "not on the toolbar" if b is None else ("disabled" if _off(b) else "enabled"), res,
                         "" if res == "PASS" else ("the House preview's Approve leg is disabled" if name == "Approve" else "")))

    # XML -----------------------------------------------------------------------------------------------------------------------------
    for field in ("ShipmentType code is DRT", "Receiving Agent key is absent", "Sending Agent key is absent"):
        rows.append(_row("X", field, "per the requirement", "not checked", "NOT_RUN", "needs a Push and the generated XML: not automated yet"))
    return rows


AGENT_TYPES = ("ReceivingForwarderAddress", "SendingForwarderAddress", "ReceivingAgent", "SendingAgent")


def check_xml(xmls: dict[str, bytes], master_no: str = "") -> list[dict]:
    """The XML Nexus pushed for a Direct BL (Job XMLs: 'NEXUS PUSH CONSOL' = Master, 'NEXUS PUSH HOUSE' = House; 'PUSH DOC' files carry documents only
    and are not judged here): ShipmentType DRT on the Master and the House, no Receiving / Sending Agent, the two waybill numbers agree.
    Returns rows of point X; NOT_RUN rows when no Job XML was given."""
    from lxml import etree
    jobs: dict[str, object] = {}
    for name, data in xmls.items():
        try:
            root = etree.fromstring(data if isinstance(data, bytes) else data.encode("utf-8"))
        except Exception as exc:
            return [_row("X", "XML is well-formed", "valid XML", f"{name}: {type(exc).__name__}", "FAIL", "the file could not be parsed")]
        trig = " ".join((e.text or "") for e in root.iter("{*}TriggerDescription")).upper()
        if "PUSH CONSOL" in trig:
            jobs["Master"] = root
        elif "PUSH HOUSE" in trig:
            jobs["House"] = root
    if not jobs:
        return [_row("X", f, "per the requirement", "not checked", "NOT_RUN", "no Job XML ('NEXUS PUSH CONSOL' / 'NEXUS PUSH HOUSE') was given: Push the job, then pass the files with --xml")
                for f in ("ShipmentType code is DRT", "Receiving Agent key is absent", "Sending Agent key is absent")]
    rows: list[dict] = []
    for kind, root in jobs.items():
        types = [e.findtext("{*}Code") or "" for e in root.iter("{*}ShipmentType")]
        rows.append(_row("X", f"{kind} XML: ShipmentType code is DRT", "DRT", ", ".join(types) or "(absent)", "PASS" if types and all(t == "DRT" for t in types) else "FAIL"))
        for label, kinds in (("Receiving Agent", ("ReceivingForwarderAddress", "ReceivingAgent")), ("Sending Agent", ("SendingForwarderAddress", "SendingAgent"))):
            found = [e.findtext("{*}OrganizationCode") or "" for e in root.iter("{*}OrganizationAddress") if (e.findtext("{*}AddressType") or "") in kinds]
            rows.append(_row("X", f"{kind} XML: {label} key is absent", "absent", ", ".join(found) or "absent", "FAIL" if found else "PASS"))
    for k in ("Master", "House"):
        if k not in jobs:
            rows.append(_row("X", f"{k} XML given", f"a 'NEXUS PUSH {'CONSOL' if k == 'Master' else 'HOUSE'}' file", "not given", "NOT_RUN", "push it and pass the file"))
    if len(jobs) == 2:
        wb = lambda r: sorted({_norm(e.text or "") for e in r.iter("{*}WayBillNumber")})
        a, b = wb(jobs["Master"]), wb(jobs["House"])
        ok = bool(a) and set(a) <= set(b)
        rows.append(_row("X", "House XML carries the Master waybill number", ", ".join(a), ", ".join(b), "PASS" if ok else "FAIL"))
    if master_no:
        got = {_norm(e.text or "") for r in jobs.values() for e in r.iter("{*}WayBillNumber")}
        rows.append(_row("X", "Waybill number equals the document's Master number", master_no, ", ".join(sorted(got)), "PASS" if _norm(master_no) in got else "FAIL"))
    return rows


def apply_xml(rows: list[dict], xml_rows: list[dict]) -> list[dict]:
    """Replaces the NOT_RUN XML rows of `evaluate` by the checked ones."""
    return [r for r in rows if not (r["section"] == POINTS["X"])] + xml_rows


def verdict(rows: list[dict]) -> str:
    rs = {r["result"] for r in rows}
    return "FAIL" if "FAIL" in rs else "REVIEW" if "REVIEW" in rs else "PASS"


def summary(rows: list[dict]) -> dict[str, dict[str, int]]:
    """{point title: {result: count}} in requirement order."""
    out: dict[str, dict[str, int]] = {t: {} for t in POINTS.values()}
    for r in rows:
        sec = out.setdefault(r["section"], {})              # a tenant's own point-1 title is not in POINTS
        sec[r["result"]] = sec.get(r["result"], 0) + 1
    order = list(POINTS)
    pos = lambda t: order.index(t.split(".", 1)[0]) if t.split(".", 1)[0] in order else order.index("X")
    return {k: v for k, v in sorted(out.items(), key=lambda kv: pos(kv[0])) if v}


def point_result(counts: dict[str, int]) -> str:
    return "FAIL" if counts.get("FAIL") else "REVIEW" if counts.get("REVIEW") else "NOT_RUN" if set(counts) == {"NOT_RUN"} else "PASS"


def format_report(results: list[dict]) -> str:
    lines: list[str] = []
    for r in results:
        lines.append(f"{r['case_id']}  {r['verdict']}  {r['ipa']}  {r['message']}".rstrip())
        for title, counts in summary(r["rows"]).items():
            lines.append(f"  {point_result(counts):8} {title}   " + ", ".join(f"{n} {k}" for k, n in counts.items()))
        for x in r["rows"]:
            if x["result"] in ("FAIL", "REVIEW"):
                lines.append(f"    {x['result']:7} {x['field']}: document/requirement says '{x['expected_from_document']}', Nexus shows '{x['shown_in_nexus']}'" + (f"  [{x['note']}]" if x["note"] else ""))
    return "\n".join(lines) or "nothing checked"


def write_markdown(cfg: Config, results: list[dict]) -> Path:
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"directbl_report_{datetime.now():%Y%m%d_%H%M%S}.md"
    L = ["# Direct BL (Air) — pass / fail report", ""]
    for r in results:
        L += [f"## {r['case_id']} — {r['verdict']} — {r['ipa']}", "", r["message"], "", "| Requirement point | Result | PASS | FAIL | REVIEW | NOT RUN |", "|---|---|---|---|---|---|"]
        for title, c in summary(r["rows"]).items():
            L.append(f"| {title} | **{point_result(c)}** | {c.get('PASS', 0)} | {c.get('FAIL', 0)} | {c.get('REVIEW', 0)} | {c.get('NOT_RUN', 0)} |")
        L += ["", "### Every check", "", "| Point | Check | Expected | Nexus shows | Result | Note |", "|---|---|---|---|---|---|"]
        for x in r["rows"]:
            cell = lambda s: str(s).replace("|", "/").replace("\n", " ")
            L.append(f"| {cell(x['section'].split('.')[0])} | {cell(x['field'])} | {cell(x['expected_from_document'])} | {cell(x['shown_in_nexus'])} | {x['result']} | {cell(x['note'])} |")
        L.append("")
    path.write_text("\n".join(L), encoding="utf-8")
    return path


# ---- the UI part (needs Nexus) ------------------------------------------------------------------------------------------------------
ROW_JS = r"""h => {
  let node = h.parentElement;
  for (let i = 0; i < 8; i++) {
    const sib = [...node.parentElement.children].filter(x => x !== node && /Master|House/.test(x.innerText));
    if (sib.length) break; node = node.parentElement; }
  const table = node.parentElement;
  const rows = [...table.children].filter(x => x !== node && /Master|House/.test(x.innerText));
  const st = e => ({label: e.getAttribute('aria-label') || e.getAttribute('title') || (e.innerText || '').trim().slice(0, 60),
     disabled: !!e.disabled, ariaDisabled: e.getAttribute('aria-disabled') || '', op: getComputedStyle(e).opacity});
  return rows.map(r => ({text: r.innerText.replace(/\s+/g, ' ').slice(0, 60),
      controls: [...r.querySelectorAll('button,input,select,[role=combobox],[role=checkbox]')].map(st)})); }"""
BAR_JS = r"""() => [...document.querySelectorAll('button')].filter(b => b.getBoundingClientRect().top < 80)
  .map(e => ({text: (e.innerText || '').trim().slice(0, 40), title: (e.getAttribute('aria-label') || e.getAttribute('title') || '').trim().slice(0, 120),
     disabled: !!e.disabled, ariaDisabled: e.getAttribute('aria-disabled') || '', op: getComputedStyle(e).opacity})).filter(x => x.text || x.title)"""


def check_one(cfg: Config, ui, case, wait_seconds: float | None) -> dict:
    from .nexus.uat import map_house_panel, map_master_panel, read_panel_inputs, read_party_ids
    v = cfg.settings["validation"]
    res = {"case_id": case.id, "ipa": "", "source": case.sample_ref or "", "verdict": "ERROR", "rows": [], "message": ""}
    cell, info = ui.wait_for_case(f"{case.id} |", wait_seconds if wait_seconds is not None else v["max_wait_seconds"], v["poll_seconds"])
    if cell is None:
        res["message"] = f"no pre-alert for {case.id} in Nexus"
        return res
    res["ipa"] = info["ipa"]
    day = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    ui.expand_row(cell)
    records = ui.read_shipment_details()                       # read BEFORE the viewer opens
    row_controls = ui._nearest_below(ui.page.get_by_text("Record Type", exact=True), ui._row_cell).evaluate(ROW_JS)
    ui.screenshot(day / "directbl_row.png")
    ui.open_viewer(cell, expanded=True)
    names: list[str] = []
    for attempt in range(4):                                   # right after a slow period the viewer header can take a while to appear
        ui.page.wait_for_timeout(3000 * (attempt + 1))
        try:
            names = ui.parent_options()
            break
        except RuntimeError:
            log.info("%s: the viewer header is not ready (attempt %d of 4)", case.id, attempt + 1)
    if not names:
        raise RuntimeError("the viewer did not open (parent dropdown not found after 4 tries)")
    parents = [n for n in names if n.startswith(("Master", "House", "Air Manifest"))]
    got: dict = {}
    for kind in ("House", "Master"):
        name = next((o for o in names if o.startswith(kind)), None)
        if name is None:
            continue
        ui.assert_viewer_job([r.get("Bill No.", "") for r in records if r.get("Record Type", "").startswith(kind)], name)
        ui.select_parent(name)
        ui.page.wait_for_timeout(1500)
        ui.screenshot(day / f"directbl_{kind.lower()}.png")
        inputs, ids = read_panel_inputs(ui.page), read_party_ids(ui.page)
        mapped = (map_house_panel if kind == "House" else map_master_panel)(inputs, ids)
        got[kind] = {"fields": mapped["fields"], "inputs": inputs, "bar": ui.page.evaluate(BAR_JS)}
    if "House" not in got or "Master" not in got:
        res["message"] = "Nexus did not create both a Master and a House" if "Master" in got else "no Master parent in the viewer"
        res["rows"] = evaluate(case.sample_ref or "", parents, records, got.get("Master", {}).get("fields", []), [], [], row_controls, [], got.get("Master", {}).get("bar", []), rules=rules_for(cfg))
        res["verdict"] = verdict(res["rows"])
        return res
    res["rows"] = evaluate(case.sample_ref or "", parents, records, got["Master"]["fields"], got["House"]["fields"], got["House"]["inputs"], row_controls,
                           got["House"]["bar"], got["Master"]["bar"], rules=rules_for(cfg))
    res["verdict"] = verdict(res["rows"])
    return res


def run_directbl_check(cfg: Config, cases: list, headless: bool = False, wait_seconds: float | None = None) -> list[dict]:
    from .nexus.session import NexusSession, SessionExpired
    from .nexus.uat import UatPages
    results: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case in cases:
                try:
                    results.append(check_one(cfg, ui, case, wait_seconds))
                except SessionExpired:
                    raise
                except Exception as exc:                          # never crash: report it against the case and carry on
                    log.exception("direct BL check of %s failed", case.id)
                    results.append({"case_id": case.id, "ipa": "", "source": "", "verdict": "ERROR", "rows": [], "message": f"{type(exc).__name__}: {str(exc).splitlines()[0][:160]}"})
    except SessionExpired as exc:
        print(f"Nexus session expired: {exc}")
    return results
