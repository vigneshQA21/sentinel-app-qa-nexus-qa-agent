import base64
import csv
import email
from email.policy import default

import openpyxl

from nexus_agent import testsuite as T
from nexus_agent.config import Config
from nexus_agent.local_sender import LocalSender
from nexus_agent.store import Store

from .test_local_sender import TAG, FakeFwd, make_pdf

HEADER = ["TC ID", "Scenario", "Document Combination", "Expected Mapping", "XML / CargoWise Validation",
          "Expected Result", "Status", "Remarks", "Quadance Job no.", "NexusJob no."]
ROWS = [
    ["REG-001", "Consolidated Mapping", "Master + House + Manifest + Invoice", "Master → Master", "xml", "ok", "", "", "FJ-0000001", "IPA/1"],
    ["REG-004", "Consolidated Mapping", "Master + Multiple Houses + Manifest", "m", "x", "ok", "", "", "FJ-0000002", ""],
    ["REG-005", "Consolidated Mapping", "Master + House", "m", "x", "ok", "", "", "FJ-0000883 - Consolidated - Shipper", ""],
    ["REG-006", "Individual Mapping", "Master + House + Manifest", "m", "x", "ok", "", "", "", ""],
    ["REG-010", "Pre-alert Neglection", "Existing + random", "m", "x", "ok", "", "", "FJ-0001163", ""],
    ["TC ID", "Test Data"],                                   # repeated header, then another block
    ["VAG-001", "Vague", "Master + House"],
]


def setup(tmp_path):
    cfg = Config(root=tmp_path, config_dir=Config().root / "config")
    cfg.settings["local_docs"].update(archive_after_send=True, skip_already_sent=True)
    (tmp_path / "knowledge_base" / "testcases").mkdir(parents=True)
    wb = openpyxl.Workbook()
    wb.active.title = "Sheet1"
    ws = wb.create_sheet("AIr Master and House - Single -")
    ws.append(HEADER)
    for r in ROWS:
        ws.append(r)
    wb.save(tmp_path / "knowledge_base" / "testcases" / "suite.xlsx")
    fwd = FakeFwd()
    return cfg, LocalSender(cfg, Store(tmp_path / "state" / "agent.db"), fwd), fwd


def good_consolidated():
    return make_pdf(["MASTER AIR WAYBILL 176-1", "AIR CARGO MANIFEST", "HAWB No: UNF1001", "COMMERCIAL INVOICE"])


def test_read_cases_scope(tmp_path):
    cfg, *_ = setup(tmp_path)
    cases = T.read_cases(cfg)
    assert [(c.id, c.mode, c.sample_ref) for c in cases] == [
        ("REG-001", "consolidated", "FJ-0000001"),      # in scope
        ("REG-005", "consolidated", "FJ-0000883"),      # FJ extracted from a longer cell
        ("REG-006", "individual", None)]                # REG-004 multi-house, REG-010 other scenario, VAG-* excluded
    assert cases[0].expected_mapping == "Master → Master"


def test_ingest_by_fj_and_case_id(tmp_path):
    cfg, *_ = setup(tmp_path)
    inbox = tmp_path / "samples" / "_inbox"
    inbox.mkdir(parents=True)
    (inbox / "FJ-0000001 - Consolidated.pdf").write_bytes(b"a")
    (inbox / "REG-006_master.pdf").write_bytes(b"b")
    (inbox / "random.pdf").write_bytes(b"c")
    filed, unmatched = T.ingest(cfg, T.read_cases(cfg))
    assert filed == {"REG-001": ["FJ-0000001 - Consolidated.pdf"], "REG-006": ["REG-006_master.pdf"]}
    assert unmatched == ["random.pdf"] and (tmp_path / "samples" / "REG-001" / "FJ-0000001 - Consolidated.pdf").exists()
    assert not (inbox / "random.pdf").unlink() and not list(inbox.iterdir())


def test_suite_dry_run_then_send_consolidated_and_individual(tmp_path):
    cfg, sender, fwd = setup(tmp_path)
    s = tmp_path / "samples"
    (s / "REG-001").mkdir(parents=True)
    (s / "REG-001" / "FJ-0000001 - Consolidated.pdf").write_bytes(good_consolidated())
    (s / "REG-006").mkdir()
    (s / "REG-006" / "REG-006_Master.pdf").write_bytes(make_pdf(["m"]))
    (s / "REG-006" / "REG-006_House.pdf").write_bytes(make_pdf(["h"]))
    cases = T.read_cases(cfg)

    rows = T.run_suite(cfg, sender, cases, dry_run=True)
    assert fwd.svc.sent == []
    assert {r["case_id"]: r["status"] for r in rows if r["status"] == "DRY_RUN"} == {"REG-001": "DRY_RUN", "REG-006": "DRY_RUN"}
    assert not [f for d in ("consolidated", "individual") for f in (tmp_path / "knowledge_base" / d).rglob("*.pdf")]
    assert len(list(s.rglob("*.pdf"))) == 3                                    # samples untouched

    rows = T.run_suite(cfg, sender, cases)
    subjects = {email.message_from_bytes(base64.urlsafe_b64decode(r), policy=default)["Subject"] for r in fwd.svc.sent}
    assert subjects == {
        TAG + " | REG-001 | Pre-Alert UNF1001 | CONSOLIDATED (MASTER+MANIFEST+HOUSE+INVOICE)",
        TAG + " | REG-006 | Pre-Alert REG-006 | INDIVIDUAL | MASTER",
        TAG + " | REG-006 | Pre-Alert REG-006 | INDIVIDUAL | HOUSE"}
    by = {(r["case_id"], r["status"]) for r in rows}
    assert ("REG-001", "SENT") in by and ("REG-005", "SAMPLE_MISSING") in by

    again = T.run_suite(cfg, sender, cases)                                    # re-run: not sent twice
    assert len(fwd.svc.sent) == 3 and {r["status"] for r in again if r["case_id"] == "REG-001"} == {"ALREADY_SENT"}
    assert not (tmp_path / "knowledge_base" / "consolidated" / "FJ-0000001 - Consolidated.pdf").exists()
    T.run_suite(cfg, sender, cases, resend=True)                               # regression re-run: sent again
    assert len(fwd.svc.sent) == 6

    path = T.write_report(cfg, rows)
    out = list(csv.DictReader(open(path, encoding="utf-8")))
    assert {"case_id", "status", "subject", "expected_mapping", "actual_nexus_result"} <= set(out[0])


def test_failed_screening_and_staging_problems(tmp_path):
    cfg, sender, fwd = setup(tmp_path)
    s = tmp_path / "samples"
    (s / "REG-001").mkdir(parents=True)
    (s / "REG-001" / "a.pdf").write_bytes(make_pdf(["COMMERCIAL INVOICE only"]))     # no master/house
    (s / "REG-005").mkdir()                                                          # consolidated case, 2 files
    (s / "REG-005" / "a.pdf").write_bytes(b"x")
    (s / "REG-005" / "b.pdf").write_bytes(b"y")
    cases = T.read_cases(cfg)
    rows = {r["case_id"]: r["status"] for r in T.run_suite(cfg, sender, cases)}
    assert rows["REG-001"] == "SCREENING_FAILED" and rows["REG-005"] == "NOT_STAGED" and fwd.svc.sent == []
    assert {r["case_id"]: r["status"] for r in T.run_suite(cfg, sender, cases, force=True)}["REG-001"] == "SENT"


def test_wait_between_cases_only_when_sending_and_next_case_has_samples(tmp_path):
    cfg, sender, fwd = setup(tmp_path)
    s = tmp_path / "samples"
    for cid in ("REG-001", "REG-005"):
        (s / cid).mkdir(parents=True)
        (s / cid / f"{cid}.pdf").write_bytes(good_consolidated())
    cases = T.read_cases(cfg)                      # REG-001, REG-005, REG-006 (no samples)
    waits = []
    T.run_suite(cfg, sender, cases, dry_run=True, interval_seconds=300, sleep=waits.append)
    assert waits == []                             # dry-run never waits
    T.run_suite(cfg, sender, cases, interval_seconds=300, sleep=waits.append)
    assert waits == [300] and len(fwd.svc.sent) == 2      # one gap: after REG-001, before REG-005; none for sample-less REG-006
    waits.clear()
    T.run_suite(cfg, sender, cases, resend=True, interval_seconds=0, sleep=waits.append)
    assert waits == []


def test_fj_number_found_next_to_underscores(tmp_path):
    cfg, sender, fwd = setup(tmp_path)
    for name in ("FJ-0000602_-_Consolidated-_DebitNote.pdf", "x FJ-0001132-Consolidated with UN.pdf"):
        f = tmp_path / name
        f.write_bytes(make_pdf(["nothing"]))
        assert sender.screen(f).ref in ("FJ-0000602", "FJ-0001132")
