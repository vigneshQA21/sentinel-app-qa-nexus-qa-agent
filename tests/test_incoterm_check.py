"""Incoterm from the invoice is accepted; the selected value must show only the code. Made-up texts."""
from nexus_agent import incoterm_check as I


def test_code_and_source():
    assert I.code_of("CIF – Cost, Insurance And Freight") == "CIF" and I.code_of("Select option") == ""
    rows = [{"label": "Incoterm", "shown_in_nexus": "CIF – Cost, Insurance And Freight", "result": "FAIL"},
            {"label": "Incoterm", "shown_in_nexus": "FOB – Free On Board", "result": "FAIL"}]
    I.fix_value_rows(rows, "BILL OF LADING ... NAGOYA", [("the invoice (x.pdf page 4)", "Unit Price CIF NAGOYA USD6.5")])
    assert rows[0]["result"] == "PASS" and "invoice" in rows[0]["note"]
    assert rows[1]["result"] == "FAIL"                                        # FOB printed nowhere: unchanged
    bill = [{"label": "Incoterm", "shown_in_nexus": "DAP", "result": "REVIEW"}]
    I.fix_value_rows(bill, "TERMS: DAP TOKYO", [])
    assert bill[0]["result"] == "PASS"


def test_selected_value_shows_only_the_code():
    [bad] = I.display_row("CIF – Cost, Insurance And Freight", "House")
    assert bad["result"] == "FAIL" and "'CIF'" in bad["expected_from_document"]
    [ok] = I.display_row("CIF", "Invoice")
    assert ok["result"] == "PASS"
    assert I.display_row("Select option", "House") == [] and I.display_row("", "House") == []


def test_invoice_incoterm_must_be_the_dropdown():
    [r] = I.display_row("CIF", "Invoice", "INPUT")
    assert r["result"] == "FAIL" and "text box" in r["note"]
    assert I.display_row("CIF", "Invoice", "SELECT")[0]["result"] == "PASS"
