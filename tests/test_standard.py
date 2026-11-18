from nexus_agent import bugprob, stdcompare as SC


def R(result, doc="", nex="", note=""):
    return {"result": result, "expected_from_document": doc, "shown_in_nexus": nex, "note": note}


def test_classes_follow_the_standard():
    assert SC.classify(R("PASS", "A", "A")) == SC.MATCH
    assert SC.classify(R("FAIL", "123 MAIN ST", "", "MISSING: empty in Nexus (Consignee), the bill prints this box")) == SC.MISSING
    assert SC.classify(R("FAIL", "24.0", "", "Nexus shows nothing")) == SC.MISSING                  # Air wording
    assert SC.classify(R("FAIL", "KGS", "K")) == SC.MISMATCH
    assert SC.classify(R("REVIEW", "", "5.2", "the document prints no volume, so this value cannot be confirmed")) == SC.NOT_IN_DOC
    assert SC.classify(R("INFO", "", "LIN_INDEL", "assigned or held by Nexus; no document value")) == SC.HELD
    assert SC.classify(R("INFO", "", "", "empty field, nothing to compare")) == SC.NOTHING
    assert SC.classify(R("KNOWN", "A", "B")) == SC.KNOWN and SC.classify(R("NOT_VERIFIABLE")) == SC.NOT_VERIFIABLE


def test_probability_is_learned_and_falls_back_to_broader_groups():
    # [document, label, nature, real]
    rec = [["Master", "Address", "mismatch", False]] * 8 + [["House", "Flight Number", "missing", True]] * 5 + [["House", "Name", "missing", True], ["House", "Name", "missing", False]]
    P = bugprob.Patterns(rec)
    p, basis = P.estimate("Master", "Shipper · Address", "mismatch")
    assert p < 0.15 and "real 0 of 8" in basis
    p, basis = P.estimate("House", "Segment 1 · Flight Number", "missing")
    assert p > 0.8 and "real 5 of" in basis
    p, basis = P.estimate("Invoice", "Date", "missing")                     # nothing specific: the broader MISSING group (all House rows) answers
    assert basis.startswith("real ") and 0.5 < p < 1
    assert bugprob.Patterns([]).estimate("Master", "X", "mismatch") == (0.5, "no history yet")
