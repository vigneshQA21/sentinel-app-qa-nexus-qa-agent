import email
from email.message import EmailMessage
from email.policy import default

from nexus_agent.checks.classification import check_classification
from nexus_agent.checks.shipper import evaluate_shipper, mawb_check_digit_ok
from nexus_agent.config import Config
from nexus_agent.gmail_forwarder import build_forward, extract_ref
from nexus_agent.xml_reconcile import reconcile, is_clean

cfg = Config()

GOOD = dict(mawb="176-12345675", hawb="UNF1001", shipper_name="Acme", shipper_address1="1 Rd",
            shipper_city="Tiruppur", shipper_country="IN", consignee_name="Nordic", pieces="12",
            gross_weight="245.50", origin="MAA", destination="ARN", etd="15-Oct-2026")


def test_mawb_check_digit():
    assert mawb_check_digit_ok("176-12345675")
    assert not mawb_check_digit_ok("176-12345676")


def test_classification_ok_and_missing():
    docs = [{"name": "a", "type": "MAWB"}, {"name": "b", "type": "HAWB"},
            {"name": "c", "type": "Commercial Invoice"}, {"name": "d", "type": "Packing List"}]
    ok, issues, _ = check_classification(docs, cfg.rules, 4)
    assert ok and not issues
    docs[2]["type"] = "Unclassified"
    ok, issues, _ = check_classification(docs, cfg.rules, 4)
    assert not ok and any("Missing invoice" in i for i in issues)


def test_classification_count_and_duplicate_master():
    docs = [{"name": "a", "type": "MAWB"}, {"name": "a2", "type": "Master AWB"}, {"name": "b", "type": "HAWB"},
            {"name": "c", "type": "Invoice"}, {"name": "d", "type": "SLI"}]
    ok, issues, _ = check_classification(docs, cfg.rules, 6)
    assert not ok
    assert any("Too many master" in i for i in issues)
    assert any("attachments were forwarded" in i for i in issues)


def test_shipper_autofix_and_corrections():
    data = {**GOOD, "shipper_country": " in ", "shipper_city": ""}
    target, edits, issues = evaluate_shipper(data, cfg.rules, {"shipper_city": "Tiruppur"})
    assert not issues
    assert target["shipper_country"] == "IN"
    assert {e["field"] for e in edits} == {"shipper_country", "shipper_city"}


def test_shipper_needs_review():
    _, _, issues = evaluate_shipper({**GOOD, "mawb": "176-12345676", "gross_weight": "0"}, cfg.rules)
    assert any("check digit" in i for i in issues) and any("gross_weight" in i for i in issues)


def test_reconcile_types():
    xml = """<TMSShipment><Header><MasterBill>176-12345675</MasterBill><HouseBill>unf1001</HouseBill></Header>
    <Shipper><Name> Acme </Name><Address1>1 Rd</Address1><City>Tiruppur</City><Country>IN</Country></Shipper>
    <Consignee><Name>Nordic</Name></Consignee><Cargo><Pieces>12</Pieces><GrossWeight>245.5</GrossWeight></Cargo>
    <Route><Origin>MAA</Origin><Destination>ARN</Destination><ETD>2026-10-15</ETD></Route></TMSShipment>"""
    rows = reconcile(xml, GOOD, cfg.xml_mapping)
    assert is_clean(rows), [r for r in rows if r["result"] != "MATCH"]
    rows = reconcile(xml.replace("<City>Tiruppur</City>", ""), {**GOOD, "pieces": "13"}, cfg.xml_mapping)
    res = {r["field"]: r["result"] for r in rows}
    assert res["shipper_city"] == "MISSING_IN_XML" and res["pieces"] == "MISMATCH"


def test_extract_ref_and_forward_keeps_attachments():
    assert extract_ref("Pre-alert HAWB UNF1001 / MAWB 17612345675", cfg) == "UNF1001"
    orig = EmailMessage()
    orig["Subject"], orig["From"], orig["To"] = "Pre-alert UNF1001", "agent@overseas.com", "ops@unifo.in"
    orig.set_content("Please find attached.")
    orig.add_attachment(b"%PDF-1.4 fake", maintype="application", subtype="pdf", filename="MAWB.pdf")
    orig.add_attachment(b"%PDF-1.4 inv", maintype="application", subtype="pdf", filename="Invoice.pdf")
    parsed = email.message_from_bytes(orig.as_bytes(), policy=default)
    fwd = build_forward(parsed, "prealert.nexus@unifo.in")
    atts = list(fwd.iter_attachments())
    assert fwd["To"] == "prealert.nexus@unifo.in" and fwd["Subject"] == "Fwd: Pre-alert UNF1001"
    assert [a.get_filename() for a in atts] == ["MAWB.pdf", "Invoice.pdf"]
    assert atts[0].get_payload(decode=True) == b"%PDF-1.4 fake"
