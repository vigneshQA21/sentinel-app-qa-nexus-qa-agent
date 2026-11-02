from nexus_agent.pdf_split import detect_parts_sea, sea_page_labels

SEA = {"house_ref_pattern": r"^[A-Z]{2,10}\d{6,}[A-Z0-9]*$", "carrier_form": ["WAYBILL", "BILL OF LADING", "SCAC"],
       "continuation_starts": ["B/L:", "PAGE:"], "invoice": ["COMMERCIAL INVOICE", "INVOICENUMBER", "INVOICE NUMBER"],
       "packing": ["PACKING LIST"], "debitnote": ["DEBIT NOTE"], "manifest": ["CARGO MANIFEST", "MANIFEST"], "head_chars": 300}


def test_carrier_waybill_is_master_and_forwarder_reference_is_house():
    texts = ["BILL OF LADING FOR OCEAN TRANSPORT SCAC MAEU\nB/L No. 1", "B/L: 1 Page : 2\nterms", "SLLTASAH611731\nJINAN HORIZON CO"]
    assert sea_page_labels(texts, SEA) == ["MBL", None, "HBL"]
    assert [(p.label, p.pages) for p in detect_parts_sea(texts, SEA)] == [("MBL", [0, 1]), ("HBL", [2])]


def test_copy_of_the_master_first_page_stays_master_and_a_different_carrier_form_is_house():
    texts = ["NON-NEGOTIABLE WAYBILL SCAC MAEU\nB/L 1", "NON-NEGOTIABLE WAYBILL SCAC MAEU\nB/L 1", "SEAWAYBILL\nREMOSA"]
    assert sea_page_labels(texts, SEA) == ["MBL", "MBL", "HBL"]


def test_supporting_documents_and_scanned_pages():
    texts = ["WAYBILL\nx", "", "ORIGINAL\nRemosa CustomerNumber OrderNumber PurchaseOrderNumber InvoiceNumber 1",
             "PACKING LIST\nManufacturer", "NINGBO\nDEBIT NOTE\nINVOICE TO"]
    assert sea_page_labels(texts, SEA) == ["MBL", None, "INVOICE", "PACKING", "DEBITNOTE"]


def test_sea_cases_are_read_and_never_mixed_into_the_air_set():
    from nexus_agent.config import Config
    from nexus_agent.testsuite import read_cases, read_cases_for, read_sea_cases
    cfg = Config("config", profile="uat")
    sea = read_sea_cases(cfg)
    assert [c.id for c in sea] == [f"SEA-REG-00{i}" for i in range(1, 9)]
    assert all(c.mode == "consolidated" and c.sample_ref for c in sea)
    assert not any(c.id.startswith("SEA-") for c in read_cases(cfg))
    assert not any(c.id.startswith("SEA-") for c in read_cases_for(cfg, None))
    assert any(c.id == "SEA-REG-002" for c in read_cases_for(cfg, {"SEA-REG-002"}))


def test_sea_value_check_reads_comma_decimals_two_digit_years_and_abbreviations():
    from nexus_agent.sea_check import _numbers, check_value
    text = "O.T.E. SPEDIZ. INTERNAZ.\nSHIPPER REMOSA SRL B/L n.264580192\n3800,00 2910,00\n29/07/26\nVOYAGE 0MXOSE1MA"
    n = _numbers(text)
    assert check_value("Gross Weight Value", "3800", text, n)[0] == "PASS"
    assert check_value("Date", "29/07/2026", text, n)[0] == "PASS"
    assert check_value("Name", "O.T.E. Spedizioni Internazionali S.r.L", text, n)[0] == "PASS"
    assert check_value("Bill No.", "264580192", text, n)[0] == "PASS"
    assert check_value("Voyage Number", "OMXOSE1MA", text, n)[0] == "FAIL"      # letter O instead of the printed digit zero
    assert check_value("Value", "0.1", text, n)[0] == "FAIL"


def test_invoice_number_under_a_table_header_row():
    from nexus_agent.docs_check import table_row_values
    raw = "Remosa\nCustomerNumber OrderNumber PurchaseOrderNumber InvoiceNumber\n104690 B34332 9070M25C49/1 CD20250534\n"
    assert "Invoice Number: CD20250534" in table_row_values(raw)
