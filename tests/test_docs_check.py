from nexus_agent import docs_check as DC

INVOICE_TEXT = """INVOICE Original Page1/4
Invoice-To
DocumentNumber: 5550001111 FABRIKAMELECTRICINFRASTRUCTURE
DocumentDate: 11AUG2026 LIMITED
172ExampleByPassRoad
600099 Chennai
Currency: USD
CustomerNumber: CUST0001
TermsofDelivery: FCACarros-France
TotalAmountofinvoice 1,742.44
OrderNumber 243170288 PO 1107380830"""

PL_TEXT = """PACKING LIST Page 1/1
Document Number 9990001 -1
Document Date 10 Aug 2026
Incoterm: FCA Carros - France
Total Gross Weight: 24 KG
CUSTOMER REF : 1107380830"""

MANIFEST_TEXT = """Air Freight Manifest - 999-12345678
HAWB: TESTHAWB0001 Declared Value: Weight: 24.000 KG
Job Ref: S1 Charges: Collect Volume: 0.360 M3
Master: Permit: Packs: 1 PLT
FABRIKAM ELECTRIC SITE ONE"""


def it(label, value, tag="INPUT"):
    return {"tag": tag, "label": label, "value": value, "readonly": False}


def rows(kind, items, raw):
    return {r["label"]: r for r in DC.compare_doc(kind, items, raw)}


def test_value_rules_id_date_amount_code_weight():
    c = DC.check_value
    assert c("id", DC.INVOICE["Invoice Number"][1], "5550001111", INVOICE_TEXT)["result"] == "PASS"
    assert c("id", DC.INVOICE["Invoice Number"][1], "5550009999", INVOICE_TEXT)["result"] == "FAIL"        # wrong number
    assert c("id", DC.INVOICE["Invoice Number"][1], "", INVOICE_TEXT)["note"].startswith("Nexus left it empty")
    assert c("date", DC.INVOICE["Invoice Date"][1], "11/08/2026", INVOICE_TEXT)["result"] == "PASS"       # 11AUG2026 == 11/08/2026
    assert c("date", DC.INVOICE["Invoice Date"][1], "12/08/2026", INVOICE_TEXT)["result"] == "FAIL"
    r = c("amount", DC.INVOICE["Grand Total"][1], "1, 742.44", INVOICE_TEXT)
    assert r["result"] == "PASS" and "formats it with a space" in r["note"]
    assert c("amount", DC.INVOICE["Grand Total"][1], "1,742.45", INVOICE_TEXT)["result"] == "FAIL"
    assert c("code", None, "FCA", INVOICE_TEXT)["result"] == "PASS"                                         # 'FCACarros' glued by the PDF
    assert c("code", None, "EXW", INVOICE_TEXT)["result"] == "FAIL"
    assert c("weight", DC.PACKING["Gross Weight"][1], "24", PL_TEXT)["result"] == "PASS"
    assert c("weight", DC.PACKING["Gross Weight"][1], "25", PL_TEXT)["result"] == "FAIL"
    assert c("id", None, "", INVOICE_TEXT)["result"] == "INFO"                                              # nothing to compare


def test_a_date_with_extra_text_is_a_fail_even_when_the_date_is_right():
    r = DC.check_value("date", DC.PACKING["Date"][1], "9990001 -1, 10 Aug 2026", PL_TEXT)
    assert r["result"] == "FAIL" and "extra text" in r["note"] and r["expected_from_document"] == "10 Aug 2026"
    assert DC.check_value("date", DC.PACKING["Date"][1], "10/08/2026", PL_TEXT)["result"] == "PASS"


def test_words_found_survives_words_the_pdf_ran_together():
    ok, note = DC.words_found("172 Example ByPass Road 600099 Chennai", INVOICE_TEXT)
    assert ok and "6/6" in note
    assert not DC.words_found("999 Elsewhere Street Nowhere", INVOICE_TEXT)[0]


def test_invoice_panel_every_field_is_listed_and_checked():
    items = [it("Invoice Number", "5550001111"), it("Invoice Date", "11/08/2026"), it("Grand Total", "1, 742.44"),
             it("Currency Code", "USD"), it("Po Number", "1107380830"), it("Gross Weight", ""),
             it("Name", "Some Seller Ltd"), it("Address", "1 Seller Road", "TEXTAREA"), it("Postal Code", "75000"),
             it("Name", "FABRIKAM ELECTRIC INFRASTRUCTURE LIMITED"), it("Address", "172 Example ByPass Road 600099 Chennai", "TEXTAREA"),
             it("Postal Code", "600099"), it("Order No", "243170288"), it("Customer No", "CUST0001"), it("Incoterm", "FCA")]
    r = rows("INVOICE", items, INVOICE_TEXT)
    assert len(DC.compare_doc("INVOICE", items, INVOICE_TEXT)) == len(items)
    for f in ("Invoice Number", "Invoice Date", "Grand Total", "Currency Code", "Po Number", "Order No", "Customer No", "Incoterm"):
        assert r[f]["result"] == "PASS", (f, r[f])
    assert r["Gross Weight"]["result"] == "INFO"
    rows_ = DC.compare_doc("INVOICE", items, INVOICE_TEXT)
    assert [x["section"] for x in rows_ if x["label"] == "Name"] == ["Seller", "Buyer"]
    assert [x["result"] for x in rows_ if x["label"] == "Name"] == ["FAIL", "PASS"]            # the seller is not on this text


def test_packing_and_manifest_panels():
    pl = rows("PACKING", [it("Packing List No", "9990001-1"), it("Date", "9990001 -1, 10 Aug 2026"), it("Gross Weight", "24"),
                          it("Incoterm", "FCA")], PL_TEXT)
    assert pl["Packing List No"]["result"] == "PASS" and pl["Date"]["result"] == "FAIL" and pl["Gross Weight"]["result"] == "PASS"
    mf = rows("MANIFEST", [it("Master Air Waybill", "999-12345678"), it("Air Waybill No", "TESTHAWB0001"), it("Pieces", "1"),
                           it("Weight", "24"), it("Name", "FABRIKAM ELECTRIC SITE ONE"), it("Address", "x", "TEXTAREA")], MANIFEST_TEXT)
    assert all(mf[k]["result"] == "PASS" for k in ("Master Air Waybill", "Air Waybill No", "Pieces", "Weight"))
    bad = rows("MANIFEST", [it("Master Air Waybill", "999-00000000"), it("Air Waybill No", "OTHER"), it("Pieces", "3"), it("Weight", "99")], MANIFEST_TEXT)
    assert all(bad[k]["result"] == "FAIL" for k in ("Master Air Waybill", "Air Waybill No", "Pieces", "Weight"))
    # the first unlabelled manifest input is the master AWB
    first = DC.compare_doc("MANIFEST", [it("", "999-12345678")], MANIFEST_TEXT)[0]
    assert first["label"] == "Master Air Waybill" and first["result"] == "PASS"


def test_currency_code_found_as_sign():
    from nexus_agent.docs_check import check_value
    r = check_value("code", None, "USD", "Total US$1,140.00")
    assert r["result"] == "PASS"
