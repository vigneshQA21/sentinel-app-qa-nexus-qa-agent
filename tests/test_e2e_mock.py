"""End-to-end: runs the real agent (Playwright) against the mock Nexus."""
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mock_nexus"))
import app as mock  # noqa: E402

from nexus_agent.agent import Agent  # noqa: E402
from nexus_agent.config import Config  # noqa: E402
from nexus_agent.models import Status  # noqa: E402

PORT = 5077


@pytest.fixture(scope="module")
def server():
    mock.APPROVAL_DELAY = 1
    srv = make_server("127.0.0.1", PORT, mock.app)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()


@pytest.fixture
def cfg(tmp_path, server, monkeypatch):
    mock.reset()
    monkeypatch.setenv("NEXUS_USER", "demo")
    monkeypatch.setenv("NEXUS_PASSWORD", "demo")
    c = Config(root=tmp_path, config_dir=Path(__file__).resolve().parent.parent / "config")
    c.settings["nexus"].update(base_url=server, home_path="/prealerts", login_path="/login")
    c.settings["timing"].update(prealert_wait_seconds=1, prealert_poll_seconds=1,
                                approval_wait_seconds=10, approval_poll_seconds=1, ui_retries=1)
    (tmp_path / "corrections").mkdir()
    return c


def test_full_run(cfg, tmp_path):
    (tmp_path / "corrections" / "UNF1005.yaml").write_text("shipper_city: Tiruppur\n")
    results, report = Agent(cfg).run(refs=["UNF1001", "UNF1002", "UNF1003", "UNF1004", "UNF1005"],
                                     use_gmail=False)
    st = {r.ref: r.status for r in results}
    assert st == {"UNF1001": Status.PASS, "UNF1002": Status.CLASSIFICATION_FAIL,
                  "UNF1003": Status.XML_MISMATCH, "UNF1004": Status.NOT_RECEIVED,
                  "UNF1005": Status.PASS}, {r.ref: r.messages for r in results}

    r1 = next(r for r in results if r.ref == "UNF1001")
    assert r1.edits[0]["field"] == "shipper_country" and mock.DB["UNF1001"]["data"]["shipper_country"] == "IN"
    assert Path(r1.evidence_dir, "tms_push.xml").exists()
    r3 = next(r for r in results if r.ref == "UNF1003")
    assert [x["field"] for x in r3.reconciliation if x["result"] == "MISMATCH"] == ["consignee_name"]
    assert (report / "summary.html").exists()
    # session was saved after the automatic login
    assert (tmp_path / "state" / "nexus_session.json").exists()


def test_dry_run_changes_nothing(cfg):
    results, _ = Agent(cfg, dry_run=True).run(refs=["UNF1001"], use_gmail=False)
    assert results[0].status == Status.DRY_RUN_OK
    assert mock.DB["UNF1001"]["data"]["shipper_country"] == " in " and mock.DB["UNF1001"]["pushed_at"] is None


def test_never_pushes_twice(cfg):
    a = Agent(cfg)
    a.run(refs=["UNF1001"], use_gmail=False)
    first_push = mock.DB["UNF1001"]["pushed_at"]
    a.store.set("UNF1001", status="APPROVAL_PENDING")    # simulate a resumed shipment
    results, _ = a.run(refs=[], use_gmail=False)
    assert results[0].status == Status.PASS and mock.DB["UNF1001"]["pushed_at"] == first_push
    assert any("Resumed" in m for m in results[0].messages)


def test_needs_review_without_correction(cfg):
    results, _ = Agent(cfg).run(refs=["UNF1005"], use_gmail=False)
    assert results[0].status == Status.NEEDS_REVIEW and mock.DB["UNF1005"]["pushed_at"] is None
