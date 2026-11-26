"""Invoice with LOGISTEED EXPRESS on it (or starting with LOGISTEED) = Debit Note -> Master; Nexus showing Invoice = KNOWN gap.
Texts are made up, shaped like the layout text of the real pages."""
from nexus_agent import debit_rule as D
from nexus_agent import label_check as L
from nexus_agent.validate import compare

NAMES, STARTS = ["LOGISTEED EXPRESS"], ["LOGISTEED"]
AGENT = "ACME FORWARDING OY\nSomestreet 1\nLOGISTEED EXPRESS LTD VAT no. X1\nTOKYO\nINVOICE\nNumber 123\nShipper Consignee"
BILL_TO = "INVOICE\nReference #: 1-2-3\nBILL to:\nLOGISTEED EXPRESS, LTD\nHARUMI"
OWN = "LOGISTEED China, Ltd.\nShanghai\nINVOICE\nNo. 55\nTo: SOME BUYER CO"
COMMERCIAL = "TAIWAN ACME CO., LTD.\nTAIPEI\nINVOICE\nNo. 231 Date: OCT.16\nFor account and risk of Messrs. ACME CO.,LTD.\nNAGOYA"
MASTER = ("Dear Customer, changes made after invoice issuance may incur a fee.\nNON-NEGOTIABLE WAYBILL\nConsignee\n"
          "LOGISTEED EXPRESS, LTD.\nTOKYO")
REAL_DN = "DEBIT NOTE SGH1\nLOGISTEED EXPRESS, LTD. INVOICE DATE 04-Nov"
ALIASES = {"DEBIT NOTE": ["DEBIT NOTE"], "INVOICE": ["INVOICE"], "MASTER": ["MBL"], "HOUSE": ["HBL"]}


def test_invoice_with_logisteed_express_is_a_debit_note():
    assert D.is_agent_bill(AGENT, NAMES, STARTS)
    assert D.is_agent_bill(BILL_TO, NAMES, STARTS)


def test_invoice_starting_with_logisteed_is_a_debit_note():
    assert D.is_agent_bill(OWN, NAMES, STARTS)


def test_other_documents_are_not():
    assert not D.is_agent_bill(COMMERCIAL, NAMES, STARTS)          # shipper's commercial invoice to the buyer
    assert not D.is_agent_bill(MASTER, NAMES, STARTS)              # mentions invoice and LOGISTEED but is a bill of lading
    assert not D.is_agent_bill(REAL_DN, NAMES, STARTS)             # already titled DEBIT NOTE
    assert not D.is_agent_bill(AGENT, [], [])                      # rule off for a tenant without names


def test_nexus_invoice_for_an_agent_debit_note_is_known_not_fail():
    expected = {"HOUSE": "House", "DEBIT NOTE": "Master"}
    actual = [{"section": "House", "name": "HBL", "type": "HBL"}, {"section": "House", "name": "INVOICE", "type": "INVOICE"}]
    gaps = {"DEBIT NOTE": ("INVOICE", "KNOWN", D.GAP_NOTE)}
    v = compare(expected, actual, ALIASES, gaps=gaps)
    dn = next(r for r in v.results if r.doc_type == "DEBIT NOTE")
    assert dn.status == "KNOWN" and "Invoice in House" in dn.detail
    assert v.passed() and not v.unexpected
    v2 = compare(expected, actual, ALIASES)                          # without the gap (a real debit note): still a failure
    assert next(r for r in v2.results if r.doc_type == "DEBIT NOTE").status == "FAIL"
    v3 = compare(expected, actual, ALIASES, gaps={"DEBIT NOTE": ("INVOICE", "FAIL", D.GAP_NOTE)})   # once Nexus has the feature
    assert not v3.passed()


def test_gap_switch():
    assert D.gap_result({}) == "KNOWN" and D.gap_result({"agent_debit_note_gap": "fail"}) == "FAIL"


def test_label_check_accepts_debit_note_label_on_agent_invoice():
    assert L.check_file("02 DEBIT NOTE - Original1.pdf", AGENT, NAMES, STARTS) == ""
    assert "DEBIT NOTE" in L.check_file("02 INVOICE - Original1.pdf", AGENT, NAMES, STARTS)
    assert L.check_file("04 INVOICE - CI.pdf", COMMERCIAL, NAMES, STARTS) == ""
