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
    assert [c.id for c in sea] == [f"SEA-REG-{i:03d}" for i in range(1, 10)]
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


def test_month_first_dates_are_read():
    from nexus_agent.sea_check import check_value
    assert check_value("Date", "21/07/2026", "ON BOARD Jul.21,2026 CONTAINER", set())[0] == "PASS"
    assert check_value("Date", "21/07/2026", "ON BOARD Jul 21, 2026", set())[0] == "PASS"


def test_casedoc_refuses_mixed_air_and_sea(tmp_path):
    import pytest
    from nexus_agent.config import Config
    from nexus_agent import casedoc
    with pytest.raises(ValueError):
        casedoc.write(Config("config"), ["REG-001", "SEA-REG-001"], workbook=tmp_path / "x.xlsx")


def test_empty_nexus_field_is_a_finding_when_the_bill_prints_a_value():
    from nexus_agent.sea_check import compare_sea
    src = {"text": "Terms\nDAP Sonipat\nPlace and date of issue\nOdense 20' Dry, S.T.C. 20,000 Cbm", "scanned": False}
    f = {"fields": [{"section": "Incoterm", "label": "Incoterm", "value": ""}, {"section": "Other", "label": "Container Type", "value": ""},
                    {"section": "Other", "label": "Seal No1", "value": ""}]}
    got = {r["label"]: r["result"] for r in compare_sea(f, src)}
    assert got == {"Incoterm": "FAIL", "Container Type": "FAIL", "Seal No1": "INFO"}
    src["scanned"] = True
    assert compare_sea(f, src)[0]["result"] == "REVIEW"


def test_exact_bill_number_does_not_match_a_longer_bill():
    import re
    exact = r"\s*".join(re.escape(c) for c in "BWSS13760427") + r"(?![A-Za-z0-9])"
    assert not re.search(exact, "BL No: BWSS 13760427A Shipper", re.I) and re.search(exact, "BL No: BWSS 13760427\nShipper", re.I)


def test_cleanup_matches_only_the_agents_own_subjects():
    from nexus_agent import cleanup as CL
    tag = "QA agent trigger / Don't delete / Regression testing | Pre-Alert FJ-0001 | CONSOLIDATED (MASTER)"
    assert CL.is_ours(f"SEA-REG-001 | {tag}", "SEA-REG-001")
    assert not CL.is_ours(f"SEA-REG-001 | {tag}", "REG-001")            # REG-001 must not match a SEA-REG-001 subject
    assert CL.is_ours(f"REG-001 | {tag}", "REG-001") and not CL.is_ours(f"REG-001 | {tag}", "SEA-REG-001")
    assert not CL.is_ours("SEA-REG-001 | Retest Nexus FJ0001382", "SEA-REG-001")   # someone else's mail with the id but no agent tag
    assert not CL.is_ours("Fwd: SEA-REG-001 | " + tag, "SEA-REG-001")
    assert CL.expand(["sea-daily"])[0] == "SEA-REG-001" and CL.expand(["reg-006", "REG-006"]) == ["REG-006"]
    import pytest
    assert CL.expand(["IPA/2420/2026-27"]) == ["IPA/2420/2026-27"]          # an approved row, named by its IPA id
    with pytest.raises(ValueError):
        CL.expand(["FJ-0001380"])


def test_case_cells_start_with_token_only():
    """'REG-002 |' must not pick up the Sea case 'SEA-REG-002 |' row (the validation took the Sea pre-alert for the Air case)."""
    from nexus_agent.nexus.uat import UatPages

    class Cell:
        def __init__(self, text): self.text = text
        def inner_text(self): return self.text

    class Loc:
        def __init__(self, cells): self.cells = cells
        def count(self): return len(self.cells)
        def nth(self, i): return self.cells[i]

    class Page:
        def locator(self, _): return Loc([Cell("SEA-REG-002 | QA agent trigger"), Cell("REG-002 | QA agent trigger")])

    ui = UatPages.__new__(UatPages)
    ui.page, ui.u = Page(), {"subject_cell": "x{token}"}
    assert [c.text for c in ui.case_cells("REG-002 |")] == ["REG-002 | QA agent trigger"]
    assert [c.text for c in ui.case_cells("SEA-REG-002 |")] == ["SEA-REG-002 | QA agent trigger"]


def test_ref_for_case_does_not_mix_air_and_sea(tmp_path):
    """REG-009 (Air) must not take the reference of SEA-REG-009 (Sea): the subject has to start with the case id."""
    from nexus_agent.store import Store
    from nexus_agent.models import PreAlert, Status
    st = Store(tmp_path / "a.db")
    st.upsert(PreAlert(ref="FJ-0001132", subject="REG-009 | QA agent trigger | Pre-Alert FJ-0001132"), Status.FORWARDED, "")
    st.upsert(PreAlert(ref="FJ-0002952", subject="SEA-REG-009 | QA agent trigger | Pre-Alert FJ-0002952"), Status.FORWARDED, "")
    assert st.ref_for_case("REG-009") == "FJ-0001132"
    assert st.ref_for_case("SEA-REG-009") == "FJ-0002952"


def test_sample_refs_read_the_fj_number_from_the_file_names():
    from nexus_agent.cleanup import sample_refs
    from nexus_agent.config import Config
    cfg = Config("config", profile="uat")
    assert sample_refs(cfg, "REG-001") == ["FJ-0000723"]
    assert sample_refs(cfg, "SEA-REG-002") == ["FJ-0001497"]


# --- the standard: document <-> Nexus shipment data (13-Nov-2026) -----------------------------------------------------------------------
from pathlib import Path as _P

_SEA009 = _P("samples/india/SEA-REG-009/FJ-0002952 - Consolidated - DAP Incoterm.pdf")


def _src009():
    from nexus_agent.pdf_split import page_texts_layout
    data = _SEA009.read_bytes()
    texts = page_texts_layout(data, ocr=False)
    return {"pdf": _SEA009, "pages": [1, 2], "text": "\n".join(texts[:2]), "scanned": False}


def _f(section, label, value=""):
    return {"section": section, "label": label, "value": value, "readonly": False}


import pytest as _pytest


@_pytest.mark.skipif(not _SEA009.exists(), reason="sample not staged")
def test_sea_empty_delivery_block_is_not_a_missing_consignee_and_same_as_consignee_is_fine():
    from nexus_agent.sea_check import compare_sea
    fields = {"fields": [_f("Consignee", "Name", "LOGISTEED INDIA PVT . LTD ."), _f("Consignee", "Address", "316 3RD FLOOR D-21 CORPORATE PARK SECTOR-21 DWARKA NEW DELHI-110077"),
                         _f("Notify Party", "Name", "SAME AS CONSIGNEE"), _f("Notify Party", "Address", "SAME AS CONSIGNEE"),
                         _f("For Delivery", "Name", ""), _f("For Delivery", "Address", "")]}
    rows = {r["field"]: r for r in compare_sea(fields, _src009())}
    assert rows["Consignee · Name"]["result"] == "PASS" and "LOGISTEED" in rows["Consignee · Name"]["expected_from_document"]    # the document's value is shown
    assert rows["For Delivery · Name"]["result"] == "INFO" and "nothing to compare" in rows["For Delivery · Name"]["note"]
    assert not [r for r in rows.values() if r["result"] in ("FAIL", "REVIEW")]


@_pytest.mark.skipif(not _SEA009.exists(), reason="sample not staged")
def test_sea_consignee_really_empty_in_nexus_is_missing_and_shows_the_bill_value():
    from nexus_agent.sea_check import compare_sea
    fields = {"fields": [_f("Consignee", "Name", ""), _f("Consignee", "Address", ""), _f("Shipper", "Name", "BLUE WATER SHIPPING A / S ( ODENSE )")]}
    rows = {r["field"]: r for r in compare_sea(fields, _src009())}
    r = rows["Consignee · Name"]
    assert r["result"] == "FAIL" and r["note"].startswith("MISSING") and "LOGISTEED INDIA PVT. LTD." in r["expected_from_document"] and "page 1" in r["expected_from_document"]
    assert rows["Shipper · Name"]["result"] == "PASS" and "BLUE WATER SHIPPING" in rows["Shipper · Name"]["expected_from_document"]


@_pytest.mark.skipif(not _SEA009.exists(), reason="sample not staged")
def test_sea_extra_empty_slot_of_a_filled_label_is_not_a_finding():
    from nexus_agent.sea_check import compare_sea
    fields = {"fields": [_f("Other", "Description", "BRAKE PARTS"), _f("Other", "Description", ""), _f("Other", "Description", "")]}
    rows = compare_sea(fields, _src009())
    assert [r["result"] for r in rows][1:] == ["INFO", "INFO"] and "extra empty slot" in rows[1]["note"]


@_pytest.mark.skipif(not _SEA009.exists(), reason="sample not staged")
def test_sea_description_empty_everywhere_is_missing_with_the_page_reference():
    from nexus_agent.sea_check import compare_sea
    rows = compare_sea({"fields": [_f("Other", "Description", "")]}, _src009())
    assert rows[0]["result"] == "FAIL" and rows[0]["note"].startswith("MISSING") and "page" in rows[0]["expected_from_document"]
