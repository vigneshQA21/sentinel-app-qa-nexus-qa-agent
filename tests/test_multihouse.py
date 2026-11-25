from pathlib import Path

import pytest

from nexus_agent.multihouse import check_parents, expected_from_pdf, verdict

SAMPLE = Path("samples/india/MH-001/FJ-0000088 - Consolidated- Multiple Houses.pdf")


def P(parent, kind, linked=(), unmatched=(), unclassified=()):
    g = lambda ls: [{"label": x, "pages": 0} for x in ls]
    return {"parent": parent, "kind": kind, "linked": g(linked), "unmatched": g(unmatched), "unclassified": g(unclassified)}


GOOD = [P("Master 098-45997836", "Master", ["MAWB"]), P("Air Manifest", "Manifest", ["AIRMANIFEST"]),
        P("House EVLHR035455", "House", ["HAWB"]), P("House EVLHR035456", "House", ["HAWB"]), P("House EVLHR035465", "House", ["HAWB"])]


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample not staged")
def test_expected_read_from_the_pdf():
    e = expected_from_pdf(SAMPLE.read_bytes())
    assert e.mawb == "098-45997836"
    assert e.hawbs == ["EVLHR035465", "EVLHR035456", "EVLHR035455"]
    assert e.duplicates == {"EVLHR035456": [6]}
    assert e.scanned_pages == [1, 2, 3]


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample not staged")
def test_correct_nexus_state_passes_and_flags_the_duplicate_for_review():
    e = expected_from_pdf(SAMPLE.read_bytes())
    cs = check_parents(GOOD, e, {"lines": ["Duplicate"]})
    assert verdict(cs) == "PASS" and not [c for c in cs if c.status == "REVIEW"]
    cs = check_parents(GOOD, e, {"lines": []})
    assert verdict(cs) == "PASS" and any(c.name == "Duplicate page flagged" and c.status == "REVIEW" for c in cs)


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample not staged")
def test_missing_extra_and_second_house_fail():
    e = expected_from_pdf(SAMPLE.read_bytes())
    missing = [p for p in GOOD if "035465" not in p["parent"]]
    assert verdict(check_parents(missing, e)) == "FAIL"
    extra = GOOD + [P("House EVLHR999999", "House", ["HAWB"])]
    cs = check_parents(extra, e)
    assert verdict(cs) == "FAIL" and any(c.name == "Unexpected House" for c in cs)
    dup = GOOD + [P("House EVLHR035456 ", "House", ["HAWB"])]
    assert verdict(check_parents(dup, e)) == "FAIL"
    assert verdict(check_parents([p for p in GOOD if p["kind"] != "Master"], e)) == "FAIL"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample not staged")
def test_duplicate_page_turned_into_a_house_with_another_number_fails_the_duplicate_check():
    e = expected_from_pdf(SAMPLE.read_bytes())
    cs = check_parents(GOOD + [P("House CAE00684799", "House", ["HAWB"])], e)
    assert any(c.name.startswith("Duplicate of") and c.status == "FAIL" for c in cs)


SEA = Path("samples/india/SEA-MH-001/FJ-0001314 - Consolidated.pdf")


@pytest.mark.skipif(not SEA.exists(), reason="sea sample not staged")
def test_sea_expectation_and_check():
    from nexus_agent.config import Config
    from nexus_agent.multihouse import expected_from_sea_pdf
    cfg = Config("config", profile="uat")
    e = expected_from_sea_pdf(SEA.read_bytes(), cfg.settings["pdf_split_sea"])
    assert e.mawb == "ONEYNB6BHJ692700" and e.hawbs == ["FGNB2608000033", "FGNB2608000091"] and not e.manifest
    good = [P("Master (ONEYNB6BHJ692700)", "Master", ["MBL"]), P("House (FGNB2608000033)", "House", ["HBL"]), P("House (FGNB2608000091)", "House", ["HBL"])]
    assert verdict(check_parents(good, e)) == "PASS"
    assert verdict(check_parents(good[:2], e)) == "FAIL"
    assert verdict(check_parents(good + [P("House (ONEYNB6BHJ692700)", "House", ["HBL"])], e)) == "FAIL"
