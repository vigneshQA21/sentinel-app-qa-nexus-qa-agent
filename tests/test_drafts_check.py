from nexus_agent import drafts_check as DC

EXP = {"master": "160-18759882", "houses": ["SJ202606239", "SJ202606240"]}


def _line(kind, bill):
    return {"Record Type": kind, "Bill No.": bill, "Shipper": "", "Status": ""}


def test_all_numbers_present_is_pass():
    rows = DC.compare("AMF-003", "IPA/1", EXP, [_line("Master draft", "160-18759882"), _line("House draft", "SJ202606239"), _line("House draft", "SJ202606240")])
    assert {r["result"] for r in rows} == {"PASS"}


def test_missing_second_house_and_wrong_master_fail():
    rows = DC.compare("AMF-003", "IPA/1", EXP, [_line("Master draft", "16018759882"), _line("House draft", "SJ202606239")])
    bad = {r["check"] for r in rows if r["result"] == "FAIL"}
    assert "House drafts count" in bad and "House draft number SJ202606240" in bad


def test_master_number_ignores_hyphen_and_spaces():
    rows = DC.compare("AMF-001", "IPA/1", {"master": "098-32591204", "houses": ["S00005958"]}, [_line("Master draft", "098 32591204"), _line("House draft", "S00005958")])
    assert all(r["result"] == "PASS" for r in rows)


def test_piece_count_glued_to_the_house_number_is_a_fail():
    rows = DC.compare("REG-011", "IPA/1", {"master": "157-69714304", "houses": ["FRA-6007 5340"]}, [_line("Master draft", "157-69714304"), _line("House draft", "6007 5340 1")])
    assert any(r["result"] == "FAIL" and r["check"].startswith("House draft number") for r in rows)
    assert any(r["check"] == "Unexpected House draft" for r in rows)
