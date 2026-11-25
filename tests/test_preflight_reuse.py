"""One Nexus search pass per run: a bill shared by several cases is searched once per preflight, and a send right after a CLEAR preflight
reuses it unless something of the case was sent since. Offline: the Nexus session and the list search are faked."""
from datetime import datetime, timedelta

import pytest

from nexus_agent import cleanup as CL
from nexus_agent.config import Config


class FakeStore:
    def __init__(self, sent=None):
        self.sent = sent or {}

    def ref_for_case(self, cid):
        return cid if cid in self.sent else None

    def last_sent_at(self, ref):
        return self.sent.get(ref)


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.settings = {**c.settings, "paths": {**c.settings["paths"], "state_dir": str(tmp_path)}}
    c.settings["local_docs"] = {**c.settings["local_docs"], "preflight_reuse_minutes": 60}
    return c


def test_clear_preflight_is_reused_within_the_window(cfg):
    t0 = datetime(2026, 11, 25, 13, 0)
    CL.remember_preflight(cfg, {"REG-001": True, "REG-002": False, "AMF-001": True}, now=t0)
    store = FakeStore({"AMF-001": t0 + timedelta(minutes=5)})            # AMF-001 was sent after the check
    got = CL.fresh_clear(cfg, ["REG-001", "REG-002", "AMF-001", "DBL-001"], store, now=t0 + timedelta(minutes=30))
    assert got == ["REG-001"]                                             # REG-002 was blocked, AMF-001 sent since, DBL-001 never checked
    assert CL.fresh_clear(cfg, ["REG-001"], store, now=t0 + timedelta(minutes=61)) == []      # too old: search again


def test_reuse_is_off_when_the_setting_is_missing_or_zero(cfg):
    CL.remember_preflight(cfg, {"REG-001": True})
    cfg.settings["local_docs"] = {k: v for k, v in cfg.settings["local_docs"].items() if k != "preflight_reuse_minutes"}
    assert CL.fresh_clear(cfg, ["REG-001"], FakeStore()) == []


def test_a_bill_shared_by_two_cases_is_searched_once(cfg, monkeypatch):
    calls = []

    class Sess:
        page = None
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def ensure_logged_in(self): pass

    def search(ui, terms):
        calls.extend(terms)
        return [{"ipa": "IPA/9/2026-27", "tab": "Pre-Alerts", "term": t, "mode": m, "subject": "someone else", "from": "", "received": ""}
                for m, t in terms if t == "098-111"]

    monkeypatch.setattr(CL, "NexusSession", Sess)
    monkeypatch.setattr(CL, "UatPages", lambda page, cfg: None)
    monkeypatch.setattr(CL, "search_terms", search)
    monkeypatch.setattr(CL, "sample_bill_numbers", lambda cfg, cid: ["098-111", "098-222"])
    monkeypatch.setattr(CL, "sample_refs", lambda cfg, cid: [f"FJ-{cid}"])
    monkeypatch.setattr(CL, "recent_ipas", lambda cfg, cid: [])
    res = CL.preflight(cfg, ["AMF-001", "AMF-002"], out=lambda *a: None)
    assert calls.count(("Bill No", "098-111")) == 1 and calls.count(("Bill No", "098-222")) == 1     # searched once for both cases
    assert [r["ipa"] for r in res["AMF-001"]] == [r["ipa"] for r in res["AMF-002"]] == ["IPA/9/2026-27"]   # both still see the existing row
    assert CL.fresh_clear(cfg, ["AMF-001", "AMF-002"], FakeStore()) == []                              # BLOCKED cases are never reused
