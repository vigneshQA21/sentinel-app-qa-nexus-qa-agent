"""Air Direct BL check: every point of the requirement is evaluated from page data (no Nexus, synthetic values)."""
from nexus_agent import directbl as DB


def _panel(prefix_house: bool = False, over: dict | None = None) -> list[dict]:
    over = over or {}
    f = [("Shipper", "Name", "ACME EXPORTS LTD"), ("Shipper", "Address", "1 EXPORT ROAD, XX"), ("Shipper", "Postal Code", ""),
         ("Consignee", "Name", "BETA TRADERS PRIVATE LIMITED"), ("Consignee", "Address", "5 IMPORT STREET, DELHI, IN"), ("Consignee", "Postal Code", "110001"),
         ("Segment 1", "From", "SZX"), ("Segment 1", "To", "DEL"), ("Segment 1", "Podctry", "IN"), ("Routing", "Final Destination Airport", "DELHI"),
         ("Cargo", "Pieces", "1"), ("Cargo", "Gross Weight", "248")]
    if prefix_house:
        f = [("House Air Waybill", "House Number (top right)", "406-91177402"), ("House Air Waybill", "House Number (bottom right)", "406-91177402")] + f
    else:
        f = [("Air Waybill", "Air Waybill Number", "406-91177402")] + f
    out = [{"section": s, "label": l, "value": over.get((s, l), v), "readonly": False} for s, l, v in f]
    return out


REC_M = {"Record Type": "Master", "Bill No.": "406-91177402", "Shipper ID": "SHP1", "Consignee ID": "CON1", "Branch": "DEL", "Status": "CW Sync Pending"}
REC_H = {**REC_M, "Record Type": "House", "Status": "Direct BL — house from Master"}


def _ctl(label, off=False):
    return {"label": label, "disabled": off, "ariaDisabled": "", "op": "0.5" if off else "1"}


HOUSE_ROW = {"text": "House Job Number", "controls": [_ctl("Job Number"), _ctl("View documents"), _ctl("Push house to CargoWise"), _ctl("Approve leg")]}
MASTER_ROW = {"text": "Master Job Number", "controls": [_ctl("Job Number"), _ctl("Shipper ID"), _ctl("Consignee ID"), _ctl("View documents"), _ctl("Push consol"), _ctl("Approve leg")]}


def _bar(**off):
    names = {"verify": "Open the HITL verification page", "reclass": "Select at least one page to re-classify", "save": "Direct-BL House is a read-only copy",
             "push": "Submit 406 (house)", "approve": "Approve leg"}
    return [{"text": "", "title": t, "disabled": off.get(k, False), "ariaDisabled": "", "op": "1"} for k, t in names.items() if k != "verify"]


def run(house_over=None, house_row=None, parents=("Master (406-91177402)", "House (406-91177402)"), bar_house=None, rec_h=None, inputs_open=0):
    hp = _panel(True, house_over or {})
    inputs = [{"readonly": i >= inputs_open} for i in range(10)]
    return DB.evaluate("406-91177402", list(parents), [REC_M, rec_h or REC_H], _panel(), hp, inputs, [MASTER_ROW, house_row or HOUSE_ROW],
                       bar_house or _bar(reclass=True, save=True, approve=False), _bar())


def by(rows, text):
    return [r for r in rows if text in r["field"]]


def test_clean_direct_bl_passes_every_automated_point():
    rows = run()
    assert [r for r in rows if r["result"] == "FAIL"] == []
    assert DB.verdict(rows) in ("PASS", "REVIEW")
    assert by(rows, "MAWB format")[0]["result"] == "PASS"
    assert by(rows, "Identified as Direct BL")[0]["result"] == "PASS"


def test_not_run_points_say_why():
    rows = run()
    nr = [r for r in rows if r["result"] == "NOT_RUN"]
    assert nr and all(r["section"].startswith("XM") for r in nr) and all(r["note"] for r in nr)       # only the XML point waits for the pushed files
    assert not any(r["section"][:2] in ("5.", "7.") for r in rows)                                         # excluded points are not in the report


def test_second_house_fails_identification():
    rows = run(parents=("Master (406-91177402)", "House (406-91177402)", "House (X123456789)"))
    assert by(rows, "Identified as Direct BL")[0]["result"] == "FAIL"


def test_house_number_must_equal_master_number():
    rows = run(house_over={("House Air Waybill", "House Number (top right)"): "999-00000000"})
    assert by(rows, "House Number (top right)")[0]["result"] == "FAIL"


def test_copied_field_difference_fails_and_names_both_values():
    rows = run(house_over={("Cargo", "Gross Weight"): "250"})
    r = by(rows, "Gross Weight")[0]
    assert (r["result"], r["expected_from_document"], r["shown_in_nexus"]) == ("FAIL", "248", "250")


def test_shipper_and_consignee_difference_fail():
    rows = run(house_over={("Shipper", "Name"): "OTHER LTD", ("Consignee", "Postal Code"): "000000"})
    assert by(rows, "Shipper · Name")[0]["result"] == "FAIL"
    assert by(rows, "Consignee = Master Consignee · Postal Code")[0]["result"] == "FAIL"


def test_blank_on_both_sides_is_a_pass():
    rows = run()
    assert by(rows, "Master Shipper -> House Shipper · Postal Code")[0]["result"] == "PASS"


def test_flyjac_or_logisteed_consignee_is_not_direct_bl():
    m = _panel(over={("Consignee", "Name"): "LOGISTEED INDIA PVT LTD"})
    rows = DB.evaluate("406-91177402", ["Master (406-91177402)", "House (406-91177402)"], [REC_M, REC_H], m, _panel(True), [{"readonly": True}], [MASTER_ROW, HOUSE_ROW],
                       _bar(reclass=True, save=True), _bar())
    assert by(rows, "not FLYJAC")[0]["result"] == "FAIL"


def test_invalid_mawb_formats():
    for bad in ("12345678901234", "12-12345678", "ABC-12345678"):
        m = _panel(over={("Air Waybill", "Air Waybill Number"): bad})
        rows = DB.evaluate("", [], [{**REC_M, "Bill No.": bad}], m, [], [], [], [], [])
        assert by(rows, "MAWB format")[0]["result"] == "FAIL", bad
    for good in ("123-12345678", "123 1234 5678", "123-1234 5678", "12312345678"):
        assert DB.MAWB_FORMAT.match(good), good


def test_destination_outside_india_fails():
    m = _panel(over={("Segment 1", "Podctry"): "SG"})
    rows = DB.evaluate("406-91177402", [], [REC_M, REC_H], m, _panel(True), [], [MASTER_ROW, HOUSE_ROW], [], [])
    assert by(rows, "Destination is India")[0]["result"] == "FAIL"


def test_house_approve_disabled_is_a_fail_with_the_dependency_note():
    row = {"text": "House Job Number", "controls": [_ctl("Job Number"), _ctl("View documents"), _ctl("Push house"), _ctl("Approve leg", off=True)]}
    rows = run(house_row=row, bar_house=_bar(reclass=True, save=True, approve=True))
    r = by(rows, "Approve action on the House row")[0]
    assert r["result"] == "FAIL" and "Master" in r["note"]
    assert by(rows, "Approve stays enabled in the preview")[0]["result"] == "FAIL"


def test_editable_house_fields_and_extra_controls_fail():
    rows = run(inputs_open=3)
    assert by(rows, "House fields are disabled")[0]["result"] == "FAIL"
    row = {"text": "House", "controls": [_ctl("Job Number"), _ctl("Shipper ID"), _ctl("View documents"), _ctl("Push house"), _ctl("Approve leg")]}
    assert by(run(house_row=row), "Only Job Number")[0]["result"] == "FAIL"


def test_enabled_save_fails_and_reclassify_is_review_not_pass():
    rows = run(bar_house=_bar(reclass=True, save=False, approve=False))
    assert by(rows, "Save is disabled")[0]["result"] == "FAIL"
    assert by(rows, "Re-classify")[0]["result"] == "REVIEW"             # disabled for 'select a page', not proof of Direct BL


def test_branch_rules():
    assert by(run(), "Branch from the Destination Airport")[0]["result"] == "PASS"
    assert by(run(rec_h={**REC_H, "Branch": ""}), "Branch on the House")[0]["result"] == "FAIL"
    assert by(run(rec_h={**REC_H, "Branch": "BOM"}), "Branch on the House")[0]["result"] == "FAIL"


def test_summary_and_report_text():
    rows = run()
    s = DB.summary(rows)
    assert list(s)[0].startswith("1.") and "XML changes" in list(s)[-1]
    text = DB.format_report([{"case_id": "DBL-001", "verdict": DB.verdict(rows), "ipa": "IPA/1/2026-27", "message": "", "rows": rows}])
    assert "DBL-001" in text and "NOT_RUN" in text


def test_field_filed_under_another_heading_in_the_house_is_found():
    m = _panel() + [{"section": "Cargo", "label": "Executed On", "value": "09/03/2026", "readonly": False}]
    h = _panel(True) + [{"section": "Reference", "label": "Executed On", "value": "09/03/2026", "readonly": False}]
    rows = DB.evaluate("406-91177402", ["Master (406-91177402)", "House (406-91177402)"], [REC_M, REC_H], m, h, [{"readonly": True}], [MASTER_ROW, HOUSE_ROW], _bar(reclass=True, save=True), _bar())
    r = by(rows, "Executed On")[0]
    assert r["result"] == "PASS" and "Reference" in r["note"]


def _xml(trigger, st="DRT", extra=""):
    return (f'<UniversalShipment xmlns="http://www.cargowise.com/Schemas/Universal/2011/11"><Shipment><DataContext><TriggerDescription>{trigger}</TriggerDescription>'
            f'</DataContext><ShipmentType><Code>{st}</Code></ShipmentType><WayBillNumber>406-9117 7402</WayBillNumber><OrganizationAddressCollection>{extra}'
            f'</OrganizationAddressCollection></Shipment></UniversalShipment>').encode()


def test_xml_clean_direct_bl_passes():
    rows = DB.check_xml({"m.xml": _xml("NEXUS PUSH CONSOL"), "h.xml": _xml("NEXUS PUSH HOUSE")}, "406-91177402")
    assert rows and all(r["result"] == "PASS" for r in rows)


def test_xml_wrong_shipment_type_or_agents_fail():
    agent = "<OrganizationAddress><AddressType>ReceivingForwarderAddress</AddressType><OrganizationCode>LAE_X</OrganizationCode></OrganizationAddress>"
    rows = DB.check_xml({"m.xml": _xml("NEXUS PUSH CONSOL", "AGT"), "h.xml": _xml("NEXUS PUSH HOUSE", extra=agent)})
    bad = {r["field"] for r in rows if r["result"] == "FAIL"}
    assert "Master XML: ShipmentType code is DRT" in bad and "House XML: Receiving Agent key is absent" in bad


def test_xml_without_job_files_is_not_run_and_doc_xml_is_ignored():
    rows = DB.check_xml({"d.xml": _xml("NEXUS PUSH DOC")})
    assert rows and all(r["result"] == "NOT_RUN" for r in rows)
