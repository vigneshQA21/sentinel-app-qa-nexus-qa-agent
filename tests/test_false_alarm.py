"""The false-alarm guard: every case below is a real row from the 27 Nov 2026 Dubai / Japan runs."""
from nexus_agent.false_alarm import guard


def _row(label, doc, shown, result="FAIL", section="Other"):
    return {"section": section, "label": label, "field": f"{section} · {label}", "expected_from_document": doc, "shown_in_nexus": shown,
            "result": result, "note": ""}


def _one(row, text=""):
    return guard([row], text)[0]["result"]


# --- false alarms that must disappear -----------------------------------------------------------------------------
def test_text_from_another_box_is_not_verifiable():
    assert _one(_row("Name", "FREIGHT PREPAID Applicable free time 13 days Combined (Detention & Demurrage)", "SHIPPER A SPA",
                     section="Shipper")) == "NOT_VERIFIABLE"
    assert _one(_row("Vessel Name", "AND VOYAGE NO (see Clause 8 & 9)", "VESSEL ONE")) == "NOT_VERIFIABLE"
    assert _one(_row("Date", "SHIPPED ON BOARD DATE", "06/04/2026")) == "NOT_VERIFIABLE"
    assert _one(_row("Name", "902 CARTONS 6,283.200KGS 64.343 CBM ========= PLASTIC CHLORINE", "CONSIGNEE E INC",
                     section="Shipper")) == "NOT_VERIFIABLE"


def test_placeholder_read_as_value():
    assert _one(_row("Port Of Discharge", "AGENT", "KHOR AL FAKKAN")) == "NOT_VERIFIABLE"
    assert _one(_row("Consignee ID", "Select", "Select Branch", section="Shipment Details")) == "NOT_VERIFIABLE"


def test_garbled_rotated_print():
    assert _one(_row("Name", "IL ES T CO NV EN U QU E LE S MA RC HA ND IS ES", "LOGISTEED Express, Ltd. - TYO", section="Consignee")) \
        == "NOT_VERIFIABLE"


def test_workflow_status_goes_to_check_by_eye():
    assert _one(_row("Status", "CW Sync Pending", "Shipper Mapping Pending", section="Shipment Details")) == "NOT_VERIFIABLE"


def test_blank_document_value_is_left_alone():
    assert _one(_row("Name", "", "", section="Shipper")) == "FAIL"          # Nexus extracted nothing from a scan (SEA-REG-009): stays


def test_no_document_value_is_info():
    assert _one(_row("Ctn Pol Ctry", "no value found in the document", "Italy")) == "INFO"
    assert _one(_row("Gross Weight", "(not available in the document)", "10", result="REVIEW", section="Cargo")) == "INFO"


def test_flight_number_after_place():
    assert _one(_row("Final Destination Airport", "DUBAI EK092-301026", "DUBAI", section="Routing")) == "PASS"
    assert _one(_row("Final Destination Airport", "DUBAI EY0086-011126 EY9149-021126", "DUBAI", section="Routing")) == "PASS"


def test_one_of_several_containers():
    text = "ABCU1234567 ML-IT2230024 40 DRY 23 PALLET\nXYZU7654321 ML-IT2230023 40 DRY 19 PALLET"
    assert _one(_row("Container No", "ABCU1234567", "XYZU7654321"), text) == "INFO"


def test_location_code_of_the_same_place():
    assert _one(_row("Ctn Pod City", "Khor Fakkan", "KLF")) == "PASS"


# --- real bugs that must stay ------------------------------------------------------------------------------------
def test_code_of_another_place_stays_fail():
    r = guard([_row("Ctn Pol City", "Genoa Vado Ligure", "BDQ")])[0]
    assert r["result"] == "FAIL" and "Vadodara" in r["note"]


def test_unknown_code_is_not_a_pass():
    assert _one(_row("Ctn Pol City", "Somewhere Port", "QQQ")) == "NOT_VERIFIABLE"


def test_real_data_differences_stay_fail():
    assert _one(_row("Airport Of Departure", "MXP MALPENSA INTERNATIONAL AIRPORT, MILAN", "MXF MALPENSA INTERNATIONAL AIRPORT, MILAN",
                     section="Routing")) == "FAIL"
    assert _one(_row("Address", "VIA ROMA 12 10121 TORINO", "VIA ROMA 1210121 TORINO", section="Shipper")) == "FAIL"
    assert _one(_row("Name", "ALPHA CARGO SOLUTION LTD.", "BETA ALPHA CARGO LIMITED.", section="Shipper")) == "FAIL"


def test_freight_field_keeps_freight_words():
    assert _one(_row("Freight Payment", "FREIGHT COLLECT", "FREIGHT PREPAID", section="Freight")) == "FAIL"


def test_container_mismatch_when_not_on_document_stays_fail():
    text = "ABCU1234567 ML-IT2230024 40 DRY 23 PALLET"
    assert _one(_row("Container No", "ABCU1234567", "XYZU7654321"), text) == "FAIL"


def test_several_candidate_postcodes():
    assert _one(_row("Postal Code", "50200, 7783, 9513", "105-6409", section="Consignee")) == "NOT_VERIFIABLE"


def test_name_box_ran_into_address():
    assert _one(_row("Name", "CONSIGNEE C FZC MARINE CITY 05130", "CONSIGNEE C FZC", section="Consignee")) == "NOT_VERIFIABLE"


def test_name_mismatch_without_address_stays_fail():
    assert _one(_row("Name", "SHIPPER B LTDA", "SHIPPER D LTDA.", section="Shipper")) == "FAIL"


def test_placeholder_address_text():
    assert _one(_row("Address", "(address on the document)", "VIA GIUSEPPE DI VITTORIO 37", result="REVIEW", section="Shipper")) == "INFO"



def test_party_record_address_difference_stays_a_finding():
    """User, 27 Nov 2026: a House Consignee address taken from the party record instead of the bill IS a bug (DXB-005 / DXB-009)."""
    rows = [_row("Party ID", "no value found in the document", "CONSCDXB1", result="INFO", section="Consignee"),
            _row("Address", "RAS AL KHAIMAH AE", "PO.BOX 5130,, MARINE CITY,, DUBAI, AE", result="REVIEW", section="Consignee")]
    assert guard(rows)[1]["result"] == "REVIEW"


def test_awb_numbers_and_same_mawb_consolidation():
    from nexus_agent.house_pick import awb_numbers, extra_rows
    assert awb_numbers("123 MI               4567 8901   HAWB MI00000001") == {"12345678901"}
    assert "12345670000" in awb_numbers("MAWB 123-45670000")
    extras = [{"Bill No.": "MI00000002", "Shipper": "SHIPPER G SRL"}]
    row = extra_rows(extras, "House", ["MI00000001"], {"MI00000002": ("DXB-011", "12345678901")})[0]
    assert row["result"] == "INFO" and "123-45678901" in row["note"]
    assert extra_rows(extras, "House", ["MI00000001"])[0]["result"] == "FAIL"      # no shared MAWB found: still reported
