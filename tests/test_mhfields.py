"""Nexus field -> document classification of the multi-house field check (no Nexus, synthetic rows)."""
from nexus_agent.mhfields import data_validation

PAGE = "HAWB No: EVLHR035465 Acron Aviation L3COMMCWY Training Solutions Limited Airbus India AIRINDDEL5 Private Limited DDP"


def row(label, doc, nex, result="FAIL", note=""):
    return {"section": "S", "label": label, "field": f"S · {label}", "expected_from_document": doc, "shown_in_nexus": nex, "result": result, "note": note}


def test_name_with_party_code_in_the_document_is_a_match():
    r = data_validation([row("Name", "Acron Aviation L3COMMCWY Training Solutions Limited", "Acron AviationTraining Solutions Limited")], PAGE)[0]
    assert r["result"] == "PASS" and r["class"] == "MATCH"


def test_value_not_on_the_page_is_not_in_document_and_other_value_is_mismatch():
    rows = data_validation([row("Address", "x", "DOOR NO 86 8TH FLOOR, Gurgaon"), row("Name", "Airbus India", "AUTRANS INDIA PRIVATE LIMITED")], PAGE)
    assert rows[0]["class"] == "NOT IN DOCUMENT" and "not available in the document" in rows[0]["note"]
    assert rows[1]["class"] == "MISMATCH"                # 3 of its 4 words are printed on the page (INDIA PRIVATE LIMITED), the name itself is another


def test_missing_in_nexus_and_held_fields():
    rows = data_validation([row("Incoterm", "DDP", ""), row("Status", "CW Sync Pending", "Consignee Mapping Pending")], PAGE)
    assert rows[0]["class"] == "MISSING"
    assert rows[1]["result"] == "FAIL"                   # a Nexus status is never looked up on the document


def test_auto_upload_never_raises_and_picks_missing_days(tmp_path, monkeypatch):
    from nexus_agent import drive_evidence as DE

    class Cfg:
        runs_dir, state_dir = tmp_path / "runs", tmp_path / "state"
    c = Cfg()
    for d in ("2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-14"):
        (c.runs_dir / d / "X").mkdir(parents=True)
        (c.runs_dir / d / "X" / "a.png").write_bytes(b"x")
    c.state_dir.mkdir()
    (c.state_dir / "drive_evidence.json").write_text('{"2026-11-10": "u", "2026-11-11": "u", "2026-11-12": "u", "2026-11-13": "u", "2026-11-14": "u"}')
    DE._state = lambda cfg: cfg.state_dir / "drive_evidence.json"
    assert DE.days_to_upload(c, "2026-11-15") == ["2026-11-15", "2026-11-14", "2026-11-13", "2026-11-12"]      # today + the last 3 days again
    (c.runs_dir / "2026-11-09" / "X").mkdir(parents=True)
    (c.runs_dir / "2026-11-09" / "X" / "a.png").write_bytes(b"x")
    assert "2026-11-09" in DE.days_to_upload(c, "2026-11-15")                                              # an old day never uploaded is caught up
    monkeypatch.setattr(DE, "upload_day", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("drive down")))
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert DE.auto_upload(c, out=lambda *_: None, attempts=2) == len(DE.days_to_upload(c))        # all fail, nothing raised
