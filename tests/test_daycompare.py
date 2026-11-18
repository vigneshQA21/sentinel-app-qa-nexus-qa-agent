import csv

from nexus_agent import daycompare as DC

VAL = ["case_id", "ref", "ipa", "nexus_status", "verdict", "appeared_after_s", "details", "evidence"]
DATA = ["case_id", "ipa", "source", "section", "field", "expected_from_document", "shown_in_nexus", "result", "note"]


def put(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})


def val(case, ipa, verdict="PASS"):
    return {"case_id": case, "ipa": ipa, "nexus_status": "CREATED_IN_NEXUS", "verdict": verdict}


def fld(case, ipa, field, result, nex="", doc=""):
    return {"case_id": case, "ipa": ipa, "field": field, "result": result, "shown_in_nexus": nex, "expected_from_document": doc}


def test_compare_marks_new_fixed_still_regressed_and_skips_other_ipas(tmp_path):
    put(tmp_path / "validate_20261110_100000.csv", VAL, [val("REG-001", "IPA/1"), val("SEA-REG-001", "IPA/9")])
    put(tmp_path / "master_data_20261110_100500.csv", DATA, [
        fld("REG-001", "IPA/1", "Shipper · Address", "FAIL", "OLD"), fld("REG-001", "IPA/1", "Cargo · Pieces", "PASS", "1"),
        fld("REG-001", "IPA/1", "Cargo · Gross Weight Unit", "FAIL", "K"), fld("REG-001", "IPA/1", "Consignee · Name", "PASS", "X"),
        fld("SEA-REG-001", "IPA/9", "Consignee · Name", "FAIL"), fld("REG-001", "IPA/0", "Other", "FAIL", "ignored: another job")])
    put(tmp_path / "validate_20261113_100000.csv", VAL, [val("REG-001", "IPA/2"), val("SEA-REG-001", "IPA/10"), val("REG-002", "IPA/3")])
    put(tmp_path / "master_data_20261113_100500.csv", DATA, [
        fld("REG-001", "IPA/2", "Shipper · Address", "PASS", "FIXED"), fld("REG-001", "IPA/2", "Cargo · Pieces", "FAIL", "2", "1"),
        fld("REG-001", "IPA/2", "Cargo · Gross Weight Unit", "FAIL", "KG"), fld("REG-001", "IPA/2", "Consignee · Name", "REVIEW", "Y"),
        fld("SEA-REG-001", "IPA/10", "Consignee · Name", "PASS"), fld("REG-002", "IPA/3", "Cargo · Pieces", "FAIL", "5")])
    res = DC.compare(tmp_path, "20261113")
    assert res["first_runs"] == ["REG-002"]
    by = {c["case_id"]: c for c in res["cases"]}
    kinds = {(c["field"]): c["kind"] for c in by["REG-001"]["changes"]}
    assert kinds == {"Shipper · Address": "FIXED", "Cargo · Pieces": "REGRESSED", "Cargo · Gross Weight Unit": "STILL", "Consignee · Name": "REGRESSED"}
    still = next(c for c in by["REG-001"]["changes"] if c["field"].endswith("Gross Weight Unit"))
    assert still["changed"] and still["nexus_before"] == "K" and still["nexus_now"] == "KG"
    assert by["REG-001"]["prev_ipa"] == "IPA/1" and by["REG-001"]["ipa"] == "IPA/2" and by["REG-001"]["counts"]["REGRESSED"] == 2
    assert by["SEA-REG-001"]["not_comparable"] and not by["REG-001"]["not_comparable"]        # Sea checker changed on 13-Nov
    text = "\n".join(DC.render(res))
    assert "REG-001: vs 10-Nov-2026" in text and "FIXED" in text and "No earlier run to compare with: REG-002" in text
