"""Stage 3: India-only rules moved to settings. India's results must be byte-identical; another tenant never inherits India's rules.
Offline: synthetic page data and temporary tenant folders (the tenant 'testland' and its values are test fixtures, not a real tenant)."""
import csv
import shutil
from pathlib import Path

import pytest
import yaml

from nexus_agent import directbl as DB
from nexus_agent.config import ROOT, Config
from nexus_agent.validate import INDIA_MASTER_SPLIT_NOTE, known_cause_note, root_causes
from tests.test_directbl import HOUSE_ROW, MASTER_ROW, REC_H, REC_M, _bar, _panel

ORIGINAL_POINT1 = [   # the rows exactly as the code wrote them before stage 3 (section, field, expected, note when failing)
    ("MAWB format (11 digits)", "406-91177402 (11-digit format)"),
    ("Destination is India", "India (DELHI on the document)"),
    ("Consignee is not FLYJAC / LOGISTEED", "not FLYJAC / LOGISTEED"),
    ("Identified as Direct BL: exactly one House, named after the Master", "1 House parent, number = Master number"),
]


def _rows(rules=DB.INDIA_RULES, over=None):
    m = _panel(over=over or {})
    return DB.evaluate("406-91177402", ["Master (406-91177402)", "House (406-91177402)"], [REC_M, REC_H], m, _panel(True),
                       [{"readonly": True}], [MASTER_ROW, HOUSE_ROW], _bar(reclass=True, save=True), _bar(), rules=rules)


def _tenant(tmp_path, name, extra=None):
    shutil.copytree(ROOT / "config", tmp_path / "config")
    d = tmp_path / "config" / name
    d.mkdir()
    for f in (ROOT / "config").glob("*.yaml"):
        shutil.copy2(f, d / f.name)
    s = yaml.safe_load((d / "settings.yaml").read_text())
    s.pop("direct_bl", None)
    s["validation"].pop("known_root_causes", None)
    s.update(tenant=name, **(extra or {}))
    s["paths"].update(state_dir=f"state/{name}", runs_dir=f"runs/{name}", corrections_dir=f"corrections/{name}")
    s["nexus"]["session_file"] = f"state/{name}/session.json"
    (d / "settings.yaml").write_text(yaml.safe_dump(s))
    return Config(root=tmp_path, tenant=name)


def test_india_point1_rows_are_unchanged():
    rows = [r for r in _rows() if r["section"].startswith("1.")]
    assert [(r["field"], r["expected_from_document"]) for r in rows] == ORIGINAL_POINT1
    assert {r["section"] for r in rows} == {DB.POINTS["1"]}
    assert DB.POINTS["1"] == "1. Direct BL identification (MAWB 11 digits, India destination, consignee not FLYJAC/LOGISTEED)"


def test_india_rules_from_settings_give_the_same_rows_as_the_built_in_defaults():
    cfg = Config()
    assert DB.rules_for(cfg) == DB.INDIA_RULES
    assert _rows(DB.rules_for(cfg)) == _rows()
    bad = _rows(DB.rules_for(cfg), {("Segment 1", "Podctry"): "SG", ("Consignee", "Name"): "LOGISTEED INDIA PVT LTD"})
    by = {r["field"]: r for r in bad}
    assert by["Destination is India"]["note"] == "destination country is not IN"
    assert by["Consignee is not FLYJAC / LOGISTEED"]["result"] == "FAIL"


@pytest.mark.skipif(not list((ROOT / "runs" / "golden" / "2026-11-20").glob("directbl_data_*.csv")), reason="Golden baseline not on this machine")
def test_india_sections_and_fields_match_the_frozen_golden_report():
    golden = next((ROOT / "runs" / "golden" / "2026-11-20").glob("directbl_data_*.csv"))
    g = {(r["section"], r["field"]) for r in csv.DictReader(open(golden, encoding="utf-8")) if r["section"].startswith("1.")}
    assert {(r["section"], r["field"]) for r in _rows(DB.rules_for(Config())) if r["section"].startswith("1.")} == g


def test_a_tenant_without_rules_gets_not_run_never_indias_rules(tmp_path):
    cfg = _tenant(tmp_path, "testland")
    assert DB.rules_for(cfg) is None
    rows = [r for r in _rows(None) if r["section"].startswith("1.")]
    assert [r["result"] for r in rows if r["field"] in ("Destination country", "Consignee not excluded")] == ["NOT_RUN", "NOT_RUN"]
    assert {r["section"] for r in rows} == {rows[0]["section"]}             # every point-1 row carries the tenant's title
    assert not any("India" in r["field"] or "FLYJAC" in r["field"] for r in rows)
    assert "no destination / consignee rules configured" in rows[0]["section"]


def test_a_tenant_with_its_own_rules_uses_only_them(tmp_path):
    cfg = _tenant(tmp_path, "testland", {"direct_bl": {"destination_country": "XX", "destination_name": "Testland",
                                                       "excluded_consignees": ["ACME"]}})
    rules = DB.rules_for(cfg)
    assert rules == {"destination_country": "XX", "destination_name": "Testland", "excluded_consignees": ["ACME"]}   # nothing merged from India
    by = {r["field"]: r for r in _rows(rules, {("Segment 1", "Podctry"): "XX"})}
    assert by["Destination is Testland"]["result"] == "PASS"
    assert by["Consignee is not ACME"]["result"] == "PASS"
    assert "India" not in " ".join(r["section"] + r["field"] for r in by.values() if r["section"].startswith("1."))


def test_summary_keeps_requirement_order_with_a_tenant_title():
    titles = list(DB.summary(_rows(None)))
    assert titles[0].startswith("1.") and titles == sorted(titles, key=lambda t: "123456789X".index(t[0]))
    assert list(DB.summary(_rows())) [0] == DB.POINTS["1"]


def test_root_cause_note_is_indias_by_default_and_absent_elsewhere(tmp_path):
    assert known_cause_note(Config()) == INDIA_MASTER_SPLIT_NOTE
    assert known_cause_note(_tenant(tmp_path, "testland")) == ""
    from nexus_agent.validate import DocResult
    miss = [DocResult("MASTER", "Master", "FAIL", "not found in Nexus")]
    india = root_causes("X", "IPA/1", [], miss, ["IPA/1", "IPA/2"], [])
    assert india[0].endswith(f"across the emails ({INDIA_MASTER_SPLIT_NOTE}).")
    other = root_causes("X", "IPA/1", [], miss, ["IPA/1", "IPA/2"], [], master_split_note="")
    assert other[0].endswith("across the emails.") and "REG-006" not in other[0]
