"""Step 1: the Golden Regression gate. Synthetic CSV reports in a temporary runs folder; no Nexus, no Gmail."""
import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from nexus_agent import golden as GD
from nexus_agent.__main__ import main
from nexus_agent.config import ROOT

VAL = ["case_id", "ref", "ipa", "nexus_status", "verdict", "appeared_after_s", "details", "evidence"]
DATA = ["case_id", "ipa", "source", "section", "field", "expected_from_document", "shown_in_nexus", "result", "note"]
DRAFT = ["case_id", "ipa", "check", "expected", "actual", "result", "note"]


def _csv(path: Path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in fields} for r in rows])


def _day(folder: Path, day: str, *, reg_mapping="PASS", reg_status="CREATED_IN_NEXUS", name="PASS", weight="FAIL", extra_field=None,
         drop_name=False, amf="PASS", dbl="PASS", with_amf007=True):
    d = day.replace("-", "")
    val = [{"case_id": "REG-002", "ipa": "IPA/1", "nexus_status": reg_status, "verdict": reg_mapping}]
    if with_amf007:
        val.append({"case_id": "AMF-007", "ipa": "IPA/2", "nexus_status": "CREATED_IN_NEXUS", "verdict": "FAIL"})
    _csv(folder / f"validate_{d}_100000.csv", VAL, val)
    rows = [] if drop_name else [{"case_id": "REG-002", "ipa": "IPA/1", "section": "Shipper", "field": "Shipper · Name", "result": name}]
    rows.append({"case_id": "REG-002", "ipa": "IPA/1", "section": "Cargo", "field": "Cargo · Gross Weight", "result": weight})
    if extra_field:
        rows.append({"case_id": "REG-002", "ipa": "IPA/1", "section": "Cargo", "field": extra_field, "result": "FAIL"})
    _csv(folder / f"master_data_{d}_100100.csv", DATA, rows)
    _csv(folder / f"drafts_data_{d}_100200.csv", DRAFT, [{"case_id": "AMF-007", "ipa": "IPA/2", "check": "Master draft exists", "result": amf}])
    _csv(folder / f"directbl_data_{d}_100300.csv", DATA, [{"case_id": "DBL-001", "ipa": "IPA/3", "section": "1. Direct BL identification",
                                                              "field": "MAWB format (11 digits)", "result": dbl}])


@pytest.fixture
def runs(tmp_path):
    r = tmp_path / "runs"
    g = r / "golden"
    _day(g / "2026-11-20", "2026-11-20")
    files = {str(p.relative_to(g)): hashlib.sha256(p.read_bytes()).hexdigest() for p in g.rglob("*.csv")}
    (g / "manifest.json").write_text(json.dumps({"tenant": "india", "frozen_on": "2026-11-25", "known_expected_fail": {"AMF-007": "manifest first"},
                                                 "cases": {"REG-002": "2026-11-20", "AMF-007": "2026-11-20", "DBL-001": "2026-11-20"},
                                                 "files_sha256": files}))
    return r


def kinds(result):
    return {(r["case_id"], r["kind"], r["field"]) for r in result["rows"]}


def test_an_identical_run_passes(runs):
    _day(runs / "_reports", "2026-11-26")
    res = GD.run(runs, ["2026-11-26"])
    assert res["verdict"] == "PASS" and set(res["per_case"].values()) == {"PASS"}
    assert ("REG-002", "KNOWN", "Cargo · Gross Weight") in kinds(res)               # failed before and still fails: reported, not blocking
    assert not any(r["case_id"] == "AMF-007" and r["field"] == "verdict" for r in res["rows"])   # its expected mapping FAIL is not even listed


def test_a_field_that_passed_and_now_fails_is_a_regression(runs):
    _day(runs / "_reports", "2026-11-26", name="FAIL")
    res = GD.run(runs, ["2026-11-26"])
    assert res["verdict"] == "FAIL" and res["per_case"]["REG-002"] == "FAIL"
    assert ("REG-002", "REGRESSION", "Shipper · Name") in kinds(res)


def test_mapping_amf_draft_and_direct_bl_regressions_block(runs):
    _day(runs / "_reports", "2026-11-26", reg_mapping="FAIL", amf="FAIL", dbl="REVIEW")
    k = kinds(GD.run(runs, ["2026-11-26"]))
    assert {("REG-002", "REGRESSION", "verdict"), ("AMF-007", "REGRESSION", "Master draft exists"),
            ("DBL-001", "REGRESSION", "1. Direct BL identification · MAWB format (11 digits)")} <= k


def test_a_passing_field_that_was_not_checked_fails_the_gate(runs):
    _day(runs / "_reports", "2026-11-26", drop_name=True)
    res = GD.run(runs, ["2026-11-26"])
    assert res["verdict"] == "FAIL" and ("REG-002", "NOT CHECKED", "Shipper · Name") in kinds(res)


def test_a_case_with_no_result_is_missing(runs):
    _day(runs / "_reports", "2026-11-26", with_amf007=False)
    (next((runs / "_reports").glob("drafts_data_*"))).unlink()
    res = GD.run(runs, ["2026-11-26"])
    assert res["per_case"]["AMF-007"] == "FAIL" and ("AMF-007", "MISSING", "") in kinds(res)


def test_not_received_or_read_error_is_incomplete_not_pass(runs):
    _day(runs / "_reports", "2026-11-26", reg_status="NOT_RECEIVED")
    assert GD.run(runs, ["2026-11-26"])["per_case"]["REG-002"] == "INCOMPLETE"
    shutil.rmtree(runs / "_reports")
    _day(runs / "_reports", "2026-11-26", name="ERROR")
    res = GD.run(runs, ["2026-11-26"])
    assert res["verdict"] == "INCOMPLETE" and ("REG-002", "ENVIRONMENT", "Shipper · Name") in kinds(res)


def test_improvements_and_new_findings_are_reported_without_blocking(runs):
    _day(runs / "_reports", "2026-11-26", weight="PASS", extra_field="Cargo · Volume")
    res = GD.run(runs, ["2026-11-26"])
    assert res["verdict"] == "PASS"
    assert {("REG-002", "IMPROVED", "Cargo · Gross Weight"), ("REG-002", "NEW FINDING", "Cargo · Volume")} <= kinds(res)


def test_the_newest_given_day_with_the_case_is_used(runs):
    _day(runs / "_reports", "2026-11-26", name="FAIL")
    _day(runs / "_reports", "2026-11-27")
    assert GD.run(runs, ["2026-11-26", "2026-11-27"])["verdict"] == "PASS"


def test_a_changed_baseline_stops_the_gate(runs):
    f = next((runs / "golden" / "2026-11-20").glob("master_data_*"))
    f.write_text(f.read_text().replace("PASS", "FAIL"))
    with pytest.raises(GD.GoldenError, match="changed or is incomplete"):
        GD.run(runs, ["2026-11-26"])
    (runs / "golden" / "manifest.json").unlink()
    with pytest.raises(GD.GoldenError, match="no Golden baseline"):
        GD.run(runs, ["2026-11-26"])


def test_cli_exit_codes_follow_the_verdict(runs, tmp_path, capsys):
    cfgdir = tmp_path / "config"
    shutil.copytree(ROOT / "config", cfgdir)
    s = yaml.safe_load((cfgdir / "settings.yaml").read_text())
    s["paths"]["runs_dir"] = str(runs)
    (cfgdir / "settings.yaml").write_text(yaml.safe_dump(s))
    _day(runs / "_reports", "2026-11-26")
    assert main(["--config", str(cfgdir), "golden", "--day", "2026-11-26"]) == 0
    _day(runs / "_reports", "2026-11-27", name="FAIL")
    assert main(["--config", str(cfgdir), "golden", "--day", "2026-11-27"]) == 1
    out = capsys.readouterr().out
    assert "GOLDEN GATE: FAIL" in out and "REGRESSION" in out and "Golden report:" in out
