"""No Debit Note in the Master Document XML (Japan sheet Sl 19). Made-up XML; the PDF text is stubbed."""
import base64

from nexus_agent import doc_xml_check as DX

AGENT = "ACME FORWARDING OY\nLOGISTEED EXPRESS LTD\nTOKYO\nINVOICE\nNumber 1"
MBL = "NON-NEGOTIABLE WAYBILL\nB/L No. X1"


def xml(target, docs, trigger="NEXUS PUSH DOC"):
    att = "".join(f"<AttachedDocument><FileName>{n}</FileName><ImageData>{base64.b64encode(t.encode()).decode()}</ImageData>"
                  f"<Type><Code>{c}</Code><Description>{d}</Description></Type></AttachedDocument>" for n, c, d, t in docs)
    return (f'<UniversalShipment xmlns="http://www.cargowise.com/Schemas/Universal/2011/11"><Shipment><DataContext><DataTargetCollection>'
            f"<DataTarget><Type>{target}</Type><Key>C1</Key></DataTarget></DataTargetCollection><TriggerDescription>{trigger}</TriggerDescription>"
            f"</DataContext><AttachedDocumentCollection>{att}</AttachedDocumentCollection></Shipment></UniversalShipment>").encode()


def stub(monkeypatch):
    monkeypatch.setattr(DX, "_pdf_pages", lambda data: [data.decode()])


def test_agent_invoice_pushed_as_invoice_in_master_xml_fails(monkeypatch):
    stub(monkeypatch)
    rows = DX.check_master_doc_xml({"m.xml": xml("ForwardingConsol", [("Master.pdf", "MBL", "MBL", MBL), ("Inv.pdf", "INV", "Invoice", AGENT)])})
    assert [r["result"] for r in rows] == ["FAIL"] and "LOGISTEED" in rows[0]["note"] and "Inv.pdf" in rows[0]["shown_in_nexus"]


def test_debit_note_label_or_title_fails(monkeypatch):
    stub(monkeypatch)
    rows = DX.check_master_doc_xml({"m.xml": xml("ForwardingConsol", [("x.pdf", "DBN", "Debit Note", "SOMETHING"),
                                                                       ("y.pdf", "OTH", "Other", "DEBIT NOTE SGH1\nTOKYO")])})
    assert [r["result"] for r in rows] == ["FAIL", "FAIL"]


def test_clean_master_passes_and_house_or_job_xml_is_not_judged(monkeypatch):
    stub(monkeypatch)
    ok = DX.check_master_doc_xml({"m.xml": xml("ForwardingConsol", [("Master.pdf", "MBL", "MBL", MBL)])})
    assert [r["result"] for r in ok] == ["PASS"]
    house = DX.check_master_doc_xml({"h.xml": xml("ForwardingShipment", [("Inv.pdf", "INV", "Invoice", AGENT)]),
                                     "j.xml": xml("ForwardingConsol", [], trigger="NEXUS PUSH CONSOL")})
    assert [r["result"] for r in house] == ["NOT_RUN"]
    assert [r["result"] for r in DX.check_master_doc_xml({})] == ["NOT_RUN"]
