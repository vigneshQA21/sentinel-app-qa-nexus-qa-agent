"""MH-002..004: the split of the multi-house sample, the phases and the omitted-House expectation (no Nexus, no network)."""
import io
import pytest
from pypdf import PdfWriter

from nexus_agent import mhphase as MP
from nexus_agent.multihouse import Expected, check_parents


def _pdf(pages: list[str]) -> bytes:
    """A PDF with one text line per page (a blank string = a scanned page without text)."""
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for t in pages:
        if t:
            c.drawString(72, 700, t)
        c.showPage()
    c.save()
    return buf.getvalue()


SAMPLE = _pdf(["", "", "", "HAWB NO: EVLHR000001 house one", "HAWB NO: EVLHR000002 house two", "HAWB NO: EVLHR000002 house two", "HAWB NO: EVLHR000003 house three"])


def test_split_master_manifest_houses_and_duplicate_left_out():
    parts, exp = MP.split(SAMPLE)
    assert parts["master"] == [0]
    assert parts["manifest"] == [1, 2]
    assert [parts[f"house{n}"] for n in (1, 2, 3)] == [[3], [4], [6]]          # the repeated page 6 (index 5) is not a House of its own
    assert "house4" not in parts
    assert exp.hawbs == ["EVLHR000001", "EVLHR000002", "EVLHR000003"]


def test_keys_for_phases():
    parts, _ = MP.split(SAMPLE)
    assert MP.keys_for("MH-002", "1", parts) == ["house1", "house2", "house3"]
    assert MP.keys_for("MH-002", "2", parts) == ["master", "manifest"]
    assert MP.keys_for("MH-003", "2", parts) == ["house3"]
    assert MP.keys_for("MH-004", "1", parts) == ["master", "manifest", "house1", "house2"]
    with pytest.raises(ValueError):
        MP.keys_for("MH-004", "2", parts)


def _parents(*houses):
    return [{"parent": "Master (098-1)", "kind": "Master"}, {"parent": "Air Manifest", "kind": "Manifest"}] + [{"parent": f"House ({h})", "kind": "House"} for h in houses]


def _exp(omitted=("EVLHR000003",)):
    return Expected(mawb="", hawbs=["EVLHR000001", "EVLHR000002"], omitted=list(omitted), manifest=True)


def test_omitted_house_absent_passes():
    res = {c.name: c for c in check_parents(_parents("EVLHR000001", "EVLHR000002"), _exp())}
    assert res["House count"].status == "PASS"
    assert res["Omitted House EVLHR000003"].status == "PASS"


def test_omitted_house_draft_is_review_not_fail():
    res = {c.name: c for c in check_parents(_parents("EVLHR000001", "EVLHR000002", "EVLHR000003"), _exp())}
    assert res["House count"].status == "PASS"                                  # the draft is reported on its own line
    assert res["Omitted House EVLHR000003"].status == "REVIEW"
    assert "Unexpected House" not in res


def test_unknown_house_still_fails():
    res = {c.name: c for c in check_parents(_parents("EVLHR000001", "EVLHR000002", "ZZZ999"), _exp())}
    assert res["House count"].status == "FAIL"
    assert res["Unexpected House"].status == "FAIL"
