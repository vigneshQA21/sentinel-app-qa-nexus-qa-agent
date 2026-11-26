"""The HTML run report shows every checked case with its screenshots: Manifest-first cases (no House parent), cases not received,
AMF drafts and Direct BL results. Built from synthetic CSVs and blank PNGs in a temporary runs folder."""
import csv
from pathlib import Path

from nexus_agent import runreport as RR


class _Store:
    def bugs_by_status(self, st): return []
    def history_rows(self): return []


def _csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def _png(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


def test_every_kind_of_case_gets_its_section_and_screenshots(tmp_path, monkeypatch):
    monkeypatch.setattr(RR, "_patterns", lambda store, reports: None)
    monkeypatch.setattr(RR, "_compare", lambda reports, day: {})
    rep, day = tmp_path / "_reports", tmp_path / "2026-11-25"
    base = {"ref": "", "appeared_after_s": "", "evidence": ""}
    _csv(rep / "validate_20261125_141149.csv", [
        {**base, "case_id": "AMF-007", "ipa": "IPA/1/2026-27", "nexus_status": "CREATED_IN_NEXUS", "verdict": "FAIL", "details": "MANIFEST: PASS (in Manifest)"},
        {**base, "case_id": "REG-002", "ipa": "", "nexus_status": "NOT_RECEIVED", "verdict": "FAIL", "details": "no pre-alert for REG-002 after 300s"}])
    _csv(rep / "drafts_data_20261125_143644.csv", [
        {"case_id": "AMF-004", "ipa": "", "check": "Pre-alert found in Nexus", "expected": "", "actual": "", "result": "FAIL",
         "note": "no pre-alert with this case id in the Pre-Alerts tab"},
        {"case_id": "AMF-001", "ipa": "IPA/2/2026-27", "check": "Master draft exists", "expected": "1", "actual": "1", "result": "PASS", "note": ""}])
    _csv(rep / "directbl_data_20261125_144352.csv", [
        {"case_id": "DBL-001", "ipa": "IPA/3/2026-27", "source": "", "section": "1. Direct BL identification", "field": "MAWB format (11 digits)",
         "expected_from_document": "x", "shown_in_nexus": "x", "result": "PASS", "note": ""}])
    _png(day / "AMF-007" / "trace_135029_IPA-1-2026-27" / "03_prealert_expanded.png")
    _png(day / "AMF-007" / "trace_135029_IPA-1-2026-27" / "04_parent_Manifest.png")        # no House parent: still shown
    _png(day / "REG-002" / "not_received.png")
    _png(day / "AMF-001" / "drafts_IPA-2-2026-27_expanded.png")
    _png(day / "DBL-001" / "directbl_row.png")
    d = RR.build(_Store(), rep, "2026-11-25")
    h = RR.html_report(d, rep)
    sec = {s.split('"')[0]: s for s in h.split('<h2 id="')[1:]}
    assert sec["AMF-007"].split("<section>")[0].count("<img") == 2
    assert "not received" in sec["REG-002"] and "not_received.png" in sec["REG-002"]
    assert "drafts_IPA-2-2026-27_expanded.png" in sec["AMF-001-amf"]
    assert "Not checked:" in sec["AMF-004-amf"] and "lookup problem" in sec["AMF-004-amf"]
    assert "directbl_row.png" in sec["DBL-001-direct"]
    assert "not validated in Nexus yet" not in h
