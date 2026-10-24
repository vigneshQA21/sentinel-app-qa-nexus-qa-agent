import io

from reportlab.pdfgen import canvas

from nexus_agent import master_check as MC
from nexus_agent.awb_extract import extract_master
from nexus_agent.nexus.uat import map_master_panel


def awb_pdf(tmp_path, mutate=None) -> str:
    """A tiny IATA-style master AWB: labels at the left edge, values below them (same anchors as real forms)."""
    p = tmp_path / "awb.pdf"
    c = canvas.Canvas(str(p), pagesize=(595, 842))
    def at(x, top, t, size=7):
        c.setFont("Helvetica", size)
        c.drawString(x, 842 - top, t)
    at(150, 20, "999NCE12345678 999-12345678")
    at(22, 53, "Shipper's Name and Address"); at(340, 53, "Issued by LUFTHANSA CARGO AG")
    for i, t in enumerate(["ACME AIR SEA", "NORTHWIND GROUP", "ZONE DE FRET", "NICE 06 22222 FR", "TE 0000000002"]):
        at(22, 66 + 9 * i, t)
    at(22, 128, "Consignee's Name and Address")
    for i, t in enumerate(["CONTOSO INDIA", "PVT. LTD.", "NO 25 32 READYMADE GARMENT COMPLEX", "SIDCO INDUSTRIAL ESTATE", "CHENNAI TN 111111 IN", "TE +10000000001"]):
        at(22, 141 + 9 * i, t)
    at(22, 198, "Issuing Carrier's Agent Name and City")
    at(22, 271, "Airport of Departure (Addr. of First Carrier) and Requested Routing"); at(22, 281, "NICE")
    at(22, 300, "To By First Carrier Routing and Destination"); at(22, 310, "FRA LH MAA LH EUR PPX X NVD NCV")
    at(22, 330, "Airport of Destination Requested Flight/Date"); at(22, 340, "CHENNAI (EX MADRAS) LH1061/22 LH758/23")
    at(22, 355, "Handling Information")
    at(22, 600, "1 24.0K Q 60.0 2.75 165.00 Consolidation as per attached list")
    at(150, 610, "Not Restricted"); at(150, 619, "HS Code: 8537109199"); at(150, 628, "VOL 0.36 M3")
    at(22, 700, "Currency Conversion Rates 21-Aug-26 NICE")
    c.save()
    return str(p)


def test_extract_master_reads_the_document_by_position(tmp_path):
    d = extract_master(awb_pdf(tmp_path))
    assert d["awb_number"] == "999-12345678" and d["origin_code"] == "NCE"
    assert d["shipper_lines"][:2] == ["ACME AIR SEA", "NORTHWIND GROUP"]
    assert "TE 0000000002" in d["shipper_lines"]                       # the phone line is part of the document block
    assert d["consignee_lines"][0] == "CONTOSO INDIA" and d["consignee_lines"][-1] == "TE +10000000001"
    assert d["departure_airport"] == "NICE" and d["destination_airport"] == "CHENNAI (EX MADRAS)"
    assert d["seg_to"] == ["FRA", "MAA"] and d["seg_carrier"] == ["LH", "LH"] and d["charges_code"] == "PP"
    assert d["flights"] == [("LH1061", 22), ("LH758", 23)]
    assert (d["pieces"], d["gross_weight"], d["gross_unit"], d["chargeable_weight"]) == ("1", "24.0", "K", "60.0")
    assert d["volume"] == ("0.36", "M3") and d["executed_on"] == "21-Aug-26"
    assert d["nature"].startswith("Consolidation as per attached list") and d["nature"].endswith("VOL 0.36 M3") and "Currency" not in d["nature"]


PANEL = [  # the order of the real Nexus 'Shipment Data' inputs
    {"tag": "INPUT", "label": "", "value": "999-12345678", "readonly": False},
    {"tag": "INPUT", "label": "Name", "value": "ACME AIR&SEA, NORTHWIND GROUP", "readonly": True},
    {"tag": "INPUT", "label": "Address", "value": "AEROPORT NICE", "readonly": True},
    {"tag": "INPUT", "label": "Postal Code", "value": "22222", "readonly": True},
    {"tag": "INPUT", "label": "Name", "value": "CONTOSO INDIA PVT . LTD .", "readonly": False},
    {"tag": "INPUT", "label": "Address", "value": "NO 25 32 READYMADE GARMENT COMPLEXSIDCO INDUSTRIAL ESTATECHENNAI TN 111111 INTE +10000000001", "readonly": False},
    {"tag": "INPUT", "label": "Postal Code", "value": "111111", "readonly": False},
    {"tag": "INPUT", "label": "Type", "value": "connecting", "readonly": False},
    {"tag": "INPUT", "label": "From", "value": "NCE", "readonly": False},
    {"tag": "INPUT", "label": "To", "value": "FRA", "readonly": False},
    {"tag": "INPUT", "label": "Polname", "value": "NICE", "readonly": False},
    {"tag": "INPUT", "label": "Polctry", "value": "FR", "readonly": False},
    {"tag": "INPUT", "label": "Podname", "value": "Frankfurt", "readonly": False},
    {"tag": "INPUT", "label": "Podctry", "value": "DE", "readonly": False},
    {"tag": "INPUT", "label": "Carrier Name", "value": "Lufthansa", "readonly": False},
    {"tag": "INPUT", "label": "Carrier Code", "value": "CLH_WW", "readonly": False},
    {"tag": "INPUT", "label": "Flight Number", "value": "LH1061", "readonly": False},
    {"tag": "INPUT", "label": "Flight Date", "value": "22/08/2026", "readonly": False},
    {"tag": "INPUT", "label": "From", "value": "FRA", "readonly": False},
    {"tag": "INPUT", "label": "To", "value": "MAA", "readonly": False},
    {"tag": "INPUT", "label": "Polname", "value": "Frankfurt", "readonly": False},
    {"tag": "INPUT", "label": "Polctry", "value": "DE", "readonly": False},
    {"tag": "INPUT", "label": "Podname", "value": "Madras", "readonly": False},
    {"tag": "INPUT", "label": "Podctry", "value": "IN", "readonly": False},
    {"tag": "INPUT", "label": "Carrier Name", "value": "Lufthansa", "readonly": False},
    {"tag": "INPUT", "label": "Carrier Code", "value": "CLH_WW", "readonly": False},
    {"tag": "INPUT", "label": "Flight Number", "value": "LH758", "readonly": False},
    {"tag": "INPUT", "label": "Flight Date", "value": "23/08/2026", "readonly": False},
    {"tag": "INPUT", "label": "Airport Of Departure", "value": "NICE", "readonly": False},
    {"tag": "INPUT", "label": "Final Destination Airport", "value": "CHENNAI ( EX MADRAS )", "readonly": False},
    {"tag": "SELECT", "label": "Freight Payment", "value": "FREIGHT PREPAID", "readonly": None},
] + [{"tag": "INPUT", "label": "", "value": v, "readonly": False} for v in
     ["1", "PCS", "24", "KGS", "60", "KGS", "Consolidation as per attached listNot Restricted HS Code: 8537109199 VOL 0.36 M3", "0.36", "CBM", "21/08/2026"]]


def test_map_master_panel_names_the_fields_in_order():
    ui = map_master_panel(PANEL)
    assert ui["awb_number"] == "999-12345678" and ui["shipper"]["name"].startswith("ACME")
    assert ui["consignee"]["postal_code"] == "111111" and [s["to"] for s in ui["segments"]] == ["FRA", "MAA"]
    assert ui["segments"][1]["flight_number"] == "LH758" and ui["freight_payment"] == "FREIGHT PREPAID"
    assert (ui["pieces"], ui["gross_weight"], ui["chargeable_weight"], ui["volume"], ui["volume_unit"], ui["executed_on"]) == \
        ("1", "24", "60", "0.36", "CBM", "21/08/2026")


def test_compare_master_passes_when_nexus_matches_the_document_and_flags_differences(tmp_path):
    doc = extract_master(awb_pdf(tmp_path))
    rows = MC.compare_master(doc, map_master_panel(PANEL))
    assert MC.verdict(rows) == "PASS", [r for r in rows if r["result"] == "FAIL"]
    by = {r["field"]: r for r in rows}
    assert by["Shipper · Address"]["result"] == "REVIEW"                     # party-master address shares only some words with the document
    assert "COMPLEXSIDCO" in by["Consignee · Address"]["note"]                # glued lines are reported

    bad = [dict(i) for i in PANEL]
    first = lambda label: next(i for i in bad if i["label"] == label)
    bad[[k for k, i in enumerate(bad) if i["label"] == "Freight Payment"][0] + 3]["value"] = "30"   # gross weight wrong
    first("From")["value"] = "ZZZ"                                            # origin airport wrong
    first("Flight Date")["value"] = "30/08/2026"                              # flight 1 day wrong
    fails = {r["field"] for r in MC.compare_master(doc, map_master_panel(bad)) if r["result"] == "FAIL"}
    assert {"Segment 1 · From", "Segment 1 · Flight Date"} <= fails
    assert "Cargo · Gross Weight" in fails


def test_missing_document_values_are_not_verifiable_never_a_pass():
    empty = {k: None for k in ("awb_number", "origin_code", "shipper_lines", "consignee_lines", "departure_airport",
                               "destination_airport", "seg_to", "seg_carrier", "currency", "charges_code", "flights",
                               "pieces", "gross_weight", "gross_unit", "chargeable_weight", "nature", "volume", "executed_on")}
    rows = MC.compare_master(empty, map_master_panel(PANEL))
    # without document values nothing may pass, except the purely internal check "segment 2 starts where segment 1 ends"
    assert {r["field"] for r in rows if r["result"] == "PASS"} <= {"Segment 2 · Polname"}


def test_glued_words_and_date_parsing():
    assert MC.glued_words(["A COMPLEX", "SIDCO ESTATE"], "A COMPLEXSIDCO ESTATE") == ["COMPLEXSIDCO"]
    assert MC.glued_words(["A COMPLEX", "SIDCO ESTATE"], "A COMPLEX SIDCO ESTATE") == []
    assert MC.parse_date("21-Aug-26") == MC.parse_date("21/08/2026") == (21, 8, 2026)


def test_every_panel_field_is_listed_in_panel_order_with_party_ids(tmp_path):
    doc = extract_master(awb_pdf(tmp_path))
    ui = map_master_panel(PANEL, {"Shippers Name And Address": "QUADIMNIC", "Consignee Name And Address": "LIN_INMAA"})
    rows = MC.compare_master(doc, ui)
    labels = [r["field"] for r in rows]
    assert labels == [f"{f['section']} · {f['label']}" for f in ui["fields"]]          # nothing dropped, same order
    assert len(labels) == len(PANEL) + 2                      # (the real panel has 43 inputs + 2 Party IDs = 45)                                                # + the two Party IDs
    by = {r["field"]: r for r in rows}
    assert by["Shipper · Party ID"]["shown_in_nexus"] == "QUADIMNIC" and by["Consignee · Party ID"]["result"] == "INFO"
    assert by["Segment 2 · Polname"]["result"] == "PASS"                                # equals segment 1's arrival airport
    assert "fields shown in Nexus" in MC.summary(rows)
    out = MC.format_report([{"case_id": "T", "verdict": "PASS", "ipa": "", "source": "", "message": "", "rows": rows}])
    assert f"ALL FIELDS SHOWN IN NEXUS ({len(rows)})" in out and "Shipper · Party ID : QUADIMNIC" in out
    assert f"=  {len(rows)} fields" in out and " 1. Air Waybill · Air Waybill Number : 999-12345678" in out


def test_internal_inconsistency_between_segments_is_a_fail(tmp_path):
    doc = extract_master(awb_pdf(tmp_path))
    items = [dict(i) for i in PANEL]
    [i for i in items if i["label"] == "Polname"][1]["value"] = "Hamburg"          # segment 2 starts where segment 1 did not end
    rows = {r["field"]: r for r in MC.compare_master(doc, map_master_panel(items))}
    assert rows["Segment 2 · Polname"]["result"] == "FAIL"


# --- Shipment Details table (Master row on the list page) ---------------------------------------------------
HEADERS = [("Record Type", 67, 145), ("Job Number", 208, 285), ("Page Nos.", 340, 403), ("Bill No.", 475, 518),
           ("Shipper", 641, 689), ("Shipper ID", 814, 878), ("Consignee", 971, 1039), ("Consignee ID", 1144, 1228),
           ("Branch", 1299, 1344), ("Job Type", 1423, 1479), ("Status", 1477, 1515), ("Actions", 1631, 1678)]
MASTER_LEAVES = [("Master", 54, 114), ("Job Number", 174, 251), ("1", 334, 339), ("999-12345678", 424, 517),
                 ("ACME AIR SEA", 584, 679), ("QUADIMNIC", 784, 860), ("CONTOSO INDIA PVT . LTD .", 924, 1105),
                 ("LIN_INMAA", 1124, 1193), ("MAA", 1264, 1294), ("New Job", 1394, 1450), ("CW Sync Pending", 1423, 1580)]


def test_assign_columns_reads_each_cell_of_the_table_row():
    from nexus_agent.nexus.uat import assign_columns
    d = assign_columns(HEADERS, MASTER_LEAVES)
    assert d["Bill No."] == "999-12345678" and d["Shipper"] == "ACME AIR SEA" and d["Shipper ID"] == "QUADIMNIC"
    assert d["Consignee ID"] == "LIN_INMAA" and d["Branch"] == "MAA" and d["Job Type"] == "New Job"
    assert d["Status"] == "CW Sync Pending" and d["Job Number"] == ""          # an empty input only shows its placeholder


def _details():
    from nexus_agent.nexus.uat import assign_columns
    return assign_columns(HEADERS, MASTER_LEAVES)


def test_master_row_checks_bill_no_parties_branch_job_type_and_status(tmp_path):
    from nexus_agent.config import Config
    cfg = Config()
    doc = extract_master(awb_pdf(tmp_path))
    ids = {"Shippers Name And Address": "QUADIMNIC", "Consignee Name And Address": "LIN_INMAA"}

    def run(details):
        ui = MC.attach_details(map_master_panel(PANEL, ids), details)         # a fresh panel each time
        return {r["field"]: r for r in MC.compare_master(doc, ui, details, cfg.settings["validation"])}

    rows = run(_details())
    for f in ("Bill No.", "Shipper", "Consignee", "Shipper ID", "Consignee ID", "Branch", "Job Type", "Status"):
        assert rows[f"Shipment Details · {f}"]["result"] == "PASS", rows[f"Shipment Details · {f}"]
    assert "MAA = Chennai" in rows["Shipment Details · Branch"]["note"]            # MAA is Chennai (Madras)

    rows = run(dict(_details(), **{"Bill No.": "999-00000000", "Branch": "BOM", "Job Type": "Existing Job", "Status": "Approved"}))
    for f in ("Bill No.", "Branch", "Job Type", "Status"):
        assert rows[f"Shipment Details · {f}"]["result"] == "FAIL", f
    assert run(dict(_details(), **{"Shipper ID": "OTHERID"}))["Shipment Details · Shipper ID"]["result"] == "FAIL"


def test_address_check_pass_review_and_fail():
    doc = "FABRIKAM ELECTRIC SITE TWO POONAMALLEE 172 BYE PASS ROAD CHENNAI 111111 IN"
    same = MC.address_check(doc, "172 Poonamallee Bye Pass Road Chennai 111111")
    assert same["result"] == "PASS" and same["note"].startswith("7/7")
    part = MC.address_check(doc, "172 Poonamallee Bye Pass Road Chennai Tamil Nadu 111111")
    assert part["result"] == "REVIEW" and "NADU" in part["note"] and "TAMIL" in part["note"]          # same place, extra words
    other = MC.address_check(doc, "SURVEY NO 4 AANGADU VILLAGE PONNERI TIRUVALLUR CHENNAI 33 IN")
    assert other["result"] == "FAIL" and other["note"].startswith("different address")                # a different place
    assert MC.address_check("", "x")["result"] == "NOT_VERIFIABLE" and MC.address_check(doc, "")["result"] == "INFO"


def test_generic_reader_for_short_forwarder_form():
    from nexus_agent.awb_extract import _generic_fill
    text = ("Check B/L\n16012345678 CHJE000001\nACME SHIPPING\nSEOUL KOREA (01234)\n"
            "INCHEON AIRPORT, KOREA FREIGHT COLLECT\nHKG CX BOM CX KRW CC CC N.V.\n"
            "BOMBAY, INDIA CX035 2026-08-22 NIL\n(1) PLT ONLY WIDGETS TOTAL 1PALLET")
    out = {}
    _generic_fill(out, text)
    assert out["awb_number"] == "160-12345678" and out["house_number"] == "CHJE000001"
    assert out["seg_to"] == ["HKG", "BOM"] and out["charges_code"] == "CC"
    assert out["destination_airport"] == "BOMBAY, INDIA" and out["executed_on"] == "2026-08-22"
    assert "WIDGETS" in out["nature"]


def test_parse_date_iso():
    from nexus_agent.master_check import parse_date
    assert parse_date("2026-08-22") == (22, 8, 2026)
