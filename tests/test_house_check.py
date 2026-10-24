from reportlab.pdfgen import canvas

from nexus_agent import house_check as HC
from nexus_agent import master_check as MC
from nexus_agent.awb_extract import extract_master
from nexus_agent.config import Config
from nexus_agent.nexus.uat import map_house_panel

HOUSE_NO = "TESTHAWB0001"


def house_pdf(tmp_path) -> str:
    """House AWB layout: routing row 'EURCC' (no space), 'As Agreed' rate, reference + TERMS, 3-decimal volume."""
    p = tmp_path / "house.pdf"
    c = canvas.Canvas(str(p), pagesize=(595, 842))
    def at(x, top, t, size=7):
        c.setFont("Helvetica", size)
        c.drawString(x, 842 - top, t)
    at(150, 20, "999NCE12345678 MAWB# 999-12345678")
    at(22, 53, "Shipper's Name and Address"); at(340, 53, "Issued by NORTHWIND CARGO AG")
    for i, t in enumerate(["FABRIKAM ELECTRIC SITE ONE", "QUAI 1 BP 147", "CARROS 06516 FR"]):
        at(22, 66 + 9 * i, t)
    at(22, 128, "Consignee's Name and Address")
    for i, t in enumerate(["FABRIKAM ELECTRIC SITE TWO", "INFRASTRUCTURE LTD", "POONAMALLEE ROAD", "CHENNAI 111111 IN"]):
        at(22, 141 + 9 * i, t)
    at(22, 198, "Issuing Carrier's Agent Name and City")
    at(22, 271, "Airport of Departure (Addr. of First Carrier) and Requested Routing Reference Number"); at(22, 281, "NICE C0000001 TERMS: EXW")
    at(22, 300, "To By First Carrier Routing and Destination"); at(22, 310, "FRA LH MAA LH EURCC X X NVD NCV")
    at(22, 330, "Airport of Destination Requested Flight/Date"); at(22, 340, "CHENNAI (EX MADRAS) LH1061/22 LH758/23")
    at(22, 355, "Handling Information")
    at(22, 600, "1 24.0K Q 60.0 As Agreed P391 Generator Rotor")
    at(150, 610, "Module"); at(150, 619, "VOL 0.360 M3")
    at(22, 700, "Currency Conversion Rates 19-Aug-26 NICE")
    c.save()
    return str(p)


def test_extractor_reads_the_house_layout(tmp_path):
    d = extract_master(house_pdf(tmp_path))
    assert d["awb_number"] == "999-12345678"                              # the master reference printed on the house page
    assert d["seg_to"] == ["FRA", "MAA"] and d["charges_code"] == "CC"     # 'EURCC' without a space
    assert (d["pieces"], d["gross_weight"], d["chargeable_weight"]) == ("1", "24.0", "60.0")
    assert d["nature"].startswith("P391 Generator Rotor") and "As Agreed" not in d["nature"] and d["volume"] == ("0.360", "M3")
    assert d["reference"] == "C0000001" and d["incoterm"] == "EXW" and d["executed_on"] == "19-Aug-26"


def item(label, value, tag="INPUT", ro=False):
    return {"tag": tag, "label": label, "value": value, "readonly": ro}


def seg(frm, to, pol, pod, carrier, code, fl, date):
    return [item("From", frm), item("To", to), item("Polname", pol), item("Polctry", "XX"), item("Podname", pod), item("Podctry", "XX"),
            item("Carrier Name", carrier), item("Carrier Code", code), item("Flight Number", fl), item("Flight Date", date)]


HOUSE_PANEL = ([item("Top Right", HOUSE_NO), item("Bottom Right", HOUSE_NO), item("", "999-12345678"),
                item("Name", "FABRIKAM ELECTRIC SITE ONE", ro=True), item("Address", "somewhere", "TEXTAREA", True), item("Postal Code", "", ro=True),
                item("Name", "FABRIKAM ELECTRIC SITE TWO", ro=True), item("Address", "elsewhere", "TEXTAREA", True), item("Postal Code", "111111", ro=True),
                item("", "ACME AIR SEA NORTHWIND GROUP ZONE", "TEXTAREA"),
                item("Freight Payment", "FREIGHT COLLECT", "SELECT"), item("Airport Of Departure", "NICE"),
                item("Final Destination Airport", "CHENNAI ( EX MADRAS )"), item("Type", "connecting")]
               + seg("NCE", "FRA", "NICE", "Frankfurt", "NORTHWIND CARGO AG", "GEC_WW", "LH1061", "22/08/2026")
               + seg("FRA", "MAA", "Frankfurt", "Madras", "SOME OTHER AIRLINE", "CLH_WW", "LH758", "23/08/2026")
               + [item("Value", "1"), item("Unit", "PCS"), item("", "24"), item("", "KGS"), item("", "60"), item("", "KGS"),
                  item("", "P391 Generator Rotor Module VOL 0.360 M3", "TEXTAREA"), item("Value", "0.36"), item("Unit", "CBM"),
                  item("Shippers Reference", "C0000001"), item("", ""), item("", "19/08/2026"), item("", ""), item("", "EXW")])
IDS = {"Shippers Name And Address": "SHIPID1", "Consignee Name And Address": "CONSID1"}
TABLE = {"Record Type": "House", "Job Number": "", "Page Nos.": "1", "Bill No.": HOUSE_NO, "Shipper": "FABRIKAM ELECTRIC",
         "Shipper ID": "SHIPID1", "Consignee": "FABRIKAM ELECTRIC SITE TWO INFRASTRUCTURE LTD", "Consignee ID": "CONSID1",
         "Branch": "MAA", "Job Type": "New Job", "Status": "CW Sync Pending"}


def run(tmp_path, panel=HOUSE_PANEL, table=TABLE):
    cfg = Config()
    doc = extract_master(house_pdf(tmp_path))
    ui = HC.attach_details(map_house_panel(panel, IDS), table)
    return {r["field"]: r for r in HC.compare_house(doc, HOUSE_NO, None, ui, table, cfg.settings["validation"])}, ui


def test_map_house_panel_names_every_field_in_order():
    ui = map_house_panel(HOUSE_PANEL, IDS)
    assert ui["house_top"] == HOUSE_NO and ui["master_ref"] == "999-12345678" and ui["agent_text"].startswith("ACME AIR")
    assert [s["to"] for s in ui["segments"]] == ["FRA", "MAA"] and ui["freight_payment"] == "FREIGHT COLLECT"
    assert (ui["pieces"], ui["gross_weight"], ui["chargeable_weight"], ui["volume"], ui["volume_unit"]) == ("1", "24", "60", "0.36", "CBM")
    assert (ui["reference"], ui["executed_on"], ui["incoterm"]) == ("C0000001", "19/08/2026", "EXW")
    assert len(ui["fields"]) == len(HOUSE_PANEL) + 2                       # + the two Party IDs, nothing dropped


def test_house_check_passes_what_matches_and_reports_what_does_not(tmp_path):
    rows, ui = run(tmp_path)
    labels = [r["field"] for r in HC.compare_house(extract_master(house_pdf(tmp_path)), HOUSE_NO, None, ui, TABLE, Config().settings["validation"])]
    assert labels == [f"{f['section']} · {f['label']}" for f in ui["fields"]]          # panel order, nothing missing
    for f in ("Shipment Details · Bill No.", "Shipment Details · Branch", "Shipment Details · Status", "Shipment Details · Shipper ID",
              "House Air Waybill · House Number (top right)", "House Air Waybill · Master AWB Reference", "Freight · Freight Payment",
              "Cargo · Gross Weight", "Cargo · Volume", "Reference · Shippers Reference", "Reference · Incoterm", "Reference · Executed On"):
        assert rows[f]["result"] == "PASS", rows[f]
    assert rows["Segment 1 · Carrier Name"]["result"] == "PASS" and rows["Segment 2 · Carrier Name"]["result"] == "INFO"
    assert rows["Segment 1 · Carrier Code"]["result"] == "INFO"                        # GEC_WW is not the IATA code LH on the document
    assert rows["Shipper · Name"]["result"] == "PASS"                                  # identical to the document block
    extra = [dict(i) for i in HOUSE_PANEL]
    extra[3]["value"] = "FABRIKAM ELECTRIC ALPES FR01"                                 # party-master name adds words
    r = run(tmp_path, extra)[0]["Shipper · Name"]
    assert r["result"] == "REVIEW" and "ALPES" in r["note"] and "FR01" in r["note"]


def test_house_check_flags_wrong_values(tmp_path):
    bad = [dict(i) for i in HOUSE_PANEL]
    for i in bad:
        if i["label"] == "Top Right": i["value"] = "OTHERHAWB"
        if i["label"] == "Freight Payment": i["value"] = "FREIGHT PREPAID"
        if i["label"] == "Postal Code" and i["value"] == "111111": i["value"] = "999999"
        if i["label"] == "Shippers Reference": i["value"] = "WRONG"
    table = dict(TABLE, **{"Status": "Invoice Mapping Pending", "Branch": "BOM", "Job Type": "Existing Job"})
    rows, _ = run(tmp_path, bad, table)
    for f in ("House Air Waybill · House Number (top right)", "Freight · Freight Payment", "Consignee · Postal Code",
              "Reference · Shippers Reference", "Shipment Details · Status", "Shipment Details · Branch", "Shipment Details · Job Type"):
        assert rows[f]["result"] == "FAIL", f
    assert "still processing" in rows["Shipment Details · Status"]["note"]
    assert MC.verdict(list(rows.values())) == "FAIL"


def test_a_party_address_that_is_a_different_place_is_a_fail(tmp_path):
    panel = [dict(i) for i in HOUSE_PANEL]
    cons = [i for i in panel if i["label"] == "Address"][1]
    cons["value"] = "SURVEY NO 4 AANGADU VILLAGE PONNERI TIRUVALLUR CHENNAI 33 IN"
    rows, _ = run(tmp_path, panel)
    r = rows["Consignee · Address"]
    assert r["result"] == "FAIL" and "different address" in r["note"]
    ok = [dict(i) for i in HOUSE_PANEL]
    [i for i in ok if i["label"] == "Address"][1]["value"] = "POONAMALLEE ROAD CHENNAI 111111"
    assert run(tmp_path, ok)[0]["Consignee · Address"]["result"] == "PASS"
