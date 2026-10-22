import sys
import threading
from pathlib import Path

import pytest
from werkzeug.serving import make_server

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "mock_nexus"))
import app as mock  # noqa: E402

from nexus_agent import validate as V  # noqa: E402
from nexus_agent.config import Config  # noqa: E402
from nexus_agent.models import PreAlert, Status  # noqa: E402
from nexus_agent.store import Store  # noqa: E402
from nexus_agent.testsuite import Case  # noqa: E402

REG001_MAPPING = "Master → Master, \nHouse → House, \nManifest → Master,\nInvoice → House ,\nPacking List → House ,"
REG001_DOCS = "Master + House + Manifest + Invoice + Packing List"
ROOT_CONFIG = Path(__file__).resolve().parent.parent / "config"
PORT = 5078


def case(cid="REG-001", mapping=REG001_MAPPING, docs=REG001_DOCS):
    return Case(cid, "Consolidated Mapping", "consolidated", docs, "FJ-0000001", mapping, "", "", "")


def test_parse_expected_reg001_text_from_the_sheet():
    cfg = Config()
    assert V.parse_expected(REG001_MAPPING, REG001_DOCS, cfg) == {
        "MASTER": "Master", "HOUSE": "House", "MANIFEST": "Master", "INVOICE": "House", "PACKING LIST": "House"}


def test_parse_expected_other_wording():
    cfg = Config()
    exp = V.parse_expected("Debit Note → Master;\n other documents → corresponding House",
                           "Master + House + Manifest + Debit Note + Invoice + random/unclassified document", cfg)
    assert exp == {"DEBIT NOTE": "Master", "MASTER": "House", "HOUSE": "House", "MANIFEST": "House", "INVOICE": "House"}
    assert V.parse_expected("Master -> Master", "Master + House", cfg) == {"MASTER": "Master"}


def test_compare_pass_wrong_section_missing_and_unexpected():
    cfg = Config()
    al = cfg.settings["validation"]["type_aliases"]
    exp = {"MASTER": "Master", "HOUSE": "House", "INVOICE": "House", "PACKING LIST": "House"}
    good = [{"section": "Master", "name": "m.pdf", "type": "Master AWB"},
            {"section": "House", "name": "h.pdf", "type": "HAWB"},
            {"section": "House", "name": "i.pdf", "type": "Commercial Invoice"},
            {"section": "House", "name": "p.pdf", "type": "Packing List"}]
    assert V.compare(exp, good, al).passed()
    bad = [dict(d) for d in good]
    bad[2]["section"] = "Master"                     # invoice under Master
    bad.pop(3)                                       # packing list missing
    bad.append({"section": "House", "name": "x.pdf", "type": "Unclassified"})
    v = V.compare(exp, bad, al)
    res = {r.doc_type: (r.status, r.detail) for r in v.results}
    assert res["INVOICE"] == ("FAIL", "found in Master, expected House")
    assert res["PACKING LIST"] == ("FAIL", "not found in Nexus")
    assert res["MASTER"][0] == "PASS" and not v.passed() and v.unexpected == ["x.pdf in House"]
    assert V.compare(exp, good + [{"section": "House", "name": "x.pdf", "type": "Unclassified"}], al).passed()
    assert not V.compare(exp, good + [{"section": "House", "name": "x.pdf", "type": "Unclassified"}], al).passed(True)


def test_store_finds_reference_of_the_last_email_for_a_case(tmp_path):
    st = Store(tmp_path / "agent.db")
    st.upsert(PreAlert(ref="TESTHAWB0001", subject="REG-001 | TAG | Pre-Alert TESTHAWB0001 | CONSOLIDATED (X)"),
              Status.FORWARDED)
    assert st.ref_for_case("REG-001") == "TESTHAWB0001" and st.ref_for_case("REG-002") is None


# --- end to end against the mock Nexus (real Playwright) --------------------------------------------
@pytest.fixture(scope="module")
def server():
    srv = make_server("127.0.0.1", PORT, mock.app)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{PORT}"
    srv.shutdown()


@pytest.fixture
def cfg(tmp_path, server, monkeypatch):
    mock.reset()
    monkeypatch.setenv("NEXUS_USER", "demo")
    monkeypatch.setenv("NEXUS_PASSWORD", "demo")
    c = Config(root=tmp_path, config_dir=ROOT_CONFIG)
    c.settings["nexus"].update(base_url=server, home_path="/prealerts", login_path="/login")
    c.settings["timing"].update(prealert_wait_seconds=1, prealert_poll_seconds=1)
    return c


def test_validate_against_mock_pass_fail_and_not_received(cfg, tmp_path):
    ok = V.run_validate(cfg, [case()], ref="UNF2001")[0]
    assert ok["verdict"] == "PASS" and ok["nexus_status"] == "CREATED_IN_NEXUS", ok
    assert (tmp_path / "runs").exists() and list((tmp_path / "runs").rglob("section_Master.png"))

    bad = V.run_validate(cfg, [case("REG-X")], ref="UNF2002")[0]
    assert bad["verdict"] == "FAIL"
    assert "INVOICE: FAIL (found in Master, expected House)" in bad["details"]
    assert "PACKING LIST: FAIL (not found in Nexus)" in bad["details"]

    gone = V.run_validate(cfg, [case("REG-Y")], ref="UNF9999")[0]
    assert gone["verdict"] == "FAIL" and gone["nexus_status"] == "NOT_RECEIVED"

    st = Store(tmp_path / "state" / "agent.db")
    assert st.get("UNF2001")["status"] == "MAPPING_PASS" and st.get("UNF2002")["status"] == "MAPPING_FAIL"
    assert V.write_report(cfg, [ok, bad, gone]).exists()


def test_validate_reports_expired_session_without_credentials(cfg, monkeypatch):
    monkeypatch.delenv("NEXUS_USER")
    monkeypatch.delenv("NEXUS_PASSWORD")
    rows = V.run_validate(cfg, [case()], ref="UNF2001")
    assert rows[0]["nexus_status"] == "SESSION_EXPIRED" and "login" in rows[0]["details"]


def test_parse_left_panel_groups_and_pages():
    from nexus_agent.nexus.uat import parse_left_panel
    heads = ["LINKED DOCUMENTS", "UNMATCHED DOCUMENTS", "UNCLASSIFIED DOCUMENTS"]
    text = "LINKED DOCUMENTS\nHAWB\nAWB\nINVOICE\nINV\nINV\nINV\nPACKINGLIST\nPKG\nUNMATCHED DOCUMENTS\nUNCLASSIFIED DOCUMENTS\nRANDOM\nXYZ"
    got = parse_left_panel(text, heads)
    assert got["linked"] == [{"label": "HAWB", "pages": 1}, {"label": "INVOICE", "pages": 3}, {"label": "PACKINGLIST", "pages": 1}]
    assert got["unmatched"] == [] and got["unclassified"][0]["label"] == "RANDOM"
    assert parse_left_panel("LINKED DOCUMENTS\nAIRMANIFEST\nMAN\nUNMATCHED DOCUMENTS\nUNCLASSIFIED DOCUMENTS", heads)["linked"] == [
        {"label": "AIRMANIFEST", "pages": 1}]


def test_reg001_as_seen_in_real_nexus_passes_and_a_wrong_parent_fails():
    cfg = Config()
    al = cfg.settings["validation"]["type_aliases"]
    exp = V.parse_expected(REG001_MAPPING, REG001_DOCS, cfg)
    seen = [{"section": "Master", "name": "MAWB", "type": "MAWB"}, {"section": "House", "name": "HAWB", "type": "HAWB"},
            {"section": "House", "name": "INVOICE", "type": "INVOICE"},
            {"section": "House", "name": "PACKINGLIST", "type": "PACKINGLIST"},
            {"section": "Manifest", "name": "AIRMANIFEST", "type": "AIRMANIFEST"}]
    accept = {"MANIFEST": {"Manifest"}}
    assert V.compare(exp, seen, al, accept).passed()
    assert not V.compare(exp, seen, al).passed()                  # without the rule the manifest parent would not count
    seen[3]["section"] = "Unmatched"                              # packing list not linked to the house
    v = V.compare(exp, seen, al, accept)
    assert not v.passed() and any(r.detail == "found in Unmatched, expected House" for r in v.results)


def test_config_profile_merges_uat_selectors_without_touching_the_mock_default():
    assert "uat" not in Config().selectors and "uat" in Config(profile="uat").selectors
    assert Config(profile="uat").selectors["login"]["username"] == "#username"       # untouched keys survive the merge


def test_plan_wait_buffer_then_poll_counted_from_the_send_time():
    # just sent: wait the 3-minute buffer, then poll until 7 minutes after sending
    assert V.plan_wait(0, 180, 420) == (180, 240)
    assert V.plan_wait(100, 180, 420) == (80, 240)           # 100 s already passed since sending
    assert V.plan_wait(200, 180, 420) == (0, 220)            # buffer over: poll the rest of the window
    assert V.plan_wait(900, 180, 420) == (0, 60)             # validating long after sending: at least one minute of polling
    assert V.plan_wait(None, 180, 420) == (0, 420)           # no send time known
    assert V.plan_wait(0, 180, 420, explicit=30) == (0, 30)  # --wait overrides


def test_validation_runs_right_after_each_case_is_sent_in_order(tmp_path):
    from nexus_agent import testsuite as T
    from .test_testsuite import ROWS, setup as suite_setup, good_consolidated
    cfg, sender, fwd = suite_setup(tmp_path)
    s = tmp_path / "samples"
    for cid in ("REG-001", "REG-005"):
        (s / cid).mkdir(parents=True)
        (s / cid / f"{cid}.pdf").write_bytes(good_consolidated())
    events = []
    orig = fwd.svc.send
    fwd.svc.send = lambda userId, body: (events.append("send"), orig(userId=userId, body=body))[1]
    T.run_suite(cfg, sender, T.read_cases(cfg), after_case=lambda case, rows: events.append(
        f"validate {case.id} sent={[r['status'] for r in rows]}"))
    # REG-006 has no samples: nothing was sent, so there is nothing to validate and no callback
    assert events == ["send", "validate REG-001 sent=['SENT']", "send", "validate REG-005 sent=['SENT']"]
