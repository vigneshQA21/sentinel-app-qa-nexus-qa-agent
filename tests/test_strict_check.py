"""Field-level precision: a field is compared with its own box, a party must be the same party (not one whose words are inside
another), Shipper and Consignee must not share a Party ID when the bill prints two parties. Offline, no real data."""
from nexus_agent import docextract as X
from nexus_agent import strict_check as S


def test_same_party_ignores_legal_words_and_branch_suffix():
    assert S.same_party("LOGISTEED Express, Ltd. - TYO", "LOGISTEED EXPRESS, LTD.")
    assert S.same_party("ACME TRADING CO., LIMITED", "ACME TRADING CO LTD")
    assert not S.same_party("CONTEC CO.,LTD.", "TAIWAN CONTEC CO.,LTD")             # words inside another party: not the same
    assert not S.same_party("EVEX GLOBAL FREIGHT LIMITED.", "GLOBAL FREIGHT SOLUTION LTD.")


def test_party_name_against_its_own_box():
    rows = [{"section": "Shipper", "label": "Name", "shown_in_nexus": "EVEX GLOBAL FREIGHT LIMITED.", "result": "REVIEW"}]
    S.party_names(rows, {}, {"shipper": ("GLOBAL FREIGHT SOLUTION LTD.\nROOM 6, HONG KONG", 1)})
    assert rows[0]["result"] == "FAIL" and "GLOBAL FREIGHT SOLUTION LTD." in rows[0]["expected_from_document"]
    ok = [{"section": "Consignee", "label": "Name", "shown_in_nexus": "LOGISTEED Express, Ltd. - TYO", "result": "PASS"}]
    S.party_names(ok, {}, {"consignee": ("LOGISTEED EXPRESS, LTD.\nTOKYO", 1)})
    assert ok[0]["result"] == "PASS"


def test_shipper_and_consignee_on_one_party_id_is_a_finding():
    rows = [{"section": "Shipper", "label": "Name", "shown_in_nexus": "CONTEC CO.,LTD."},
            {"section": "Shipper", "label": "Party ID", "shown_in_nexus": "PID001"},
            {"section": "Consignee", "label": "Party ID", "shown_in_nexus": "PID001"}]
    boxes = {"shipper": ("TAIWAN CONTEC CO.,LTD\nTAIPEI", 3), "consignee": ("CONTEC CO.,LTD\nAICHI", 3)}
    [r] = S.same_party_id(rows, {}, boxes)
    assert r["result"] == "FAIL" and "PID001" in r["shown_in_nexus"] and "TAIWAN CONTEC" in r["expected_from_document"]
    same = {"shipper": ("ACME CO LTD\nX", 1), "consignee": ("ACME CO., LTD.\nY", 1)}
    assert S.same_party_id(rows, {}, same) == []                                   # the bill prints the same party twice
    other = rows[:2] + [{"section": "Consignee", "label": "Party ID", "shown_in_nexus": "PID002"}]
    assert S.same_party_id(other, {}, boxes) == []


def test_a_field_must_be_inside_its_own_box(monkeypatch):
    calls = {"Place Of Delivery": (f"{X.NO_VALUE} (the box 'PLACE OF DELIVERY' on page 1 is blank)", "by position: the box is blank"),
             "Port Of Loading": ("HAMBURG", "by position from the box 'PORT OF LOADING' on page 1"),
             "Port Of Discharge": ("NAGOYA", "by position from the box 'PORT OF DISCHARGE' on page 1"),
             "Vessel Name": ("OOCL PORTUGAL", "matching line on the document")}
    monkeypatch.setattr(X, "extract_from_source", lambda src, label, value: calls[label])
    rows = [{"label": k, "shown_in_nexus": v, "result": "PASS"} for k, v in
            [("Place Of Delivery", "NAGOYA"), ("Port Of Loading", "NAGOYA"), ("Port Of Discharge", "NAGOYA"), ("Vessel Name", "OOCL X")]]
    S.box_fields(rows, {})
    assert [r["result"] for r in rows] == ["INFO", "FAIL", "PASS", "PASS"]        # no box located for the vessel: unchanged
    assert "Port Of Discharge" in rows[0]["note"]                                  # blank Place of Delivery filled from POD: accepted


def test_blank_place_of_delivery_not_from_the_port_of_discharge_stays_review(monkeypatch):
    calls = {"Place Of Delivery": (f"{X.NO_VALUE} (the box 'PLACE OF DELIVERY' on page 1 is blank)", "by position: the box is blank"),
             "Port Of Discharge": ("NAGOYA", "by position from the box 'PORT OF DISCHARGE' on page 1")}
    monkeypatch.setattr(X, "extract_from_source", lambda src, label, value: calls[label])
    rows = [{"label": "Place Of Delivery", "shown_in_nexus": "OSAKA", "result": "PASS"}]
    S.box_fields(rows, {})
    assert rows[0]["result"] == "REVIEW"
    blank = {"Place Of Delivery": calls["Place Of Delivery"], "Port Of Discharge": (f"{X.NO_VALUE} (blank)", "by position: the box is blank")}
    monkeypatch.setattr(X, "extract_from_source", lambda src, label, value: blank[label])
    rows = [{"label": "Place Of Delivery", "shown_in_nexus": "NAGOYA", "result": "PASS"}]
    S.box_fields(rows, {})
    assert rows[0]["result"] == "REVIEW"                                            # POD blank too: nothing to fill from


def test_party_box_read_as_one_line_is_cut_after_the_name():
    assert S.same_party("VAARNII OY", "VAARNII OY Sorvaajankatu 15 00880 HELSINKI Finland")
    assert S.same_party("AIRLOG GROUP OY", "Waybill AIRLOG GROUP OY B/L no.: HAMEENTIE 19")          # heading word skipped
    assert S.same_party("WELCOME CO., LTD.", "WELCOME Co., Ltd 5-11-11 Himonya, Meguro-ku")
    assert not S.same_party("CONTEC CO.,LTD.", "TAIWAN CONTEC CO.,LTD 9F.,NO.738")                # a word before the name counts
    assert not S.same_party("SERVIMEX LOGISTICA LTDA.", "SERPA LOGISTICA LTDA (CARGO AGENT ONLY)")


def test_scanned_bill_is_not_judged_box_by_box(monkeypatch):
    monkeypatch.setattr(X, "extract_from_source", lambda src, label, value: ("Flnal Deednatiou", "by position from the box"))
    rows = [{"label": "Place Of Delivery", "shown_in_nexus": "OSAKA , JAPAN", "result": "PASS"}]
    S.box_fields(rows, {"scanned": True})
    assert rows[0]["result"] == "PASS"
