"""One document split across Linked and Unmatched is reported (IPA/12: booking confirmation 1 page linked, 3 pages unmatched)."""
from nexus_agent.validate import split_documents


def P(parent, linked=(), unmatched=()):
    return {"parent": parent, "kind": parent.split(" ")[0], "linked": [{"label": l, "pages": n} for l, n in linked],
            "unmatched": [{"label": l, "pages": n} for l, n in unmatched], "unclassified": []}


def test_split_shipper_document_is_found():
    parents = [P("Master (273896072)", [("MBL", 1)], [("SHIPPERDOC", 3)]),
               P("House (4239079/26)", [("HBL", 1), ("SHIPPERDOC", 1)], [("SHIPPERDOC", 3)])]
    s = split_documents(parents)
    assert len(s) == 1 and s[0]["label"] == "SHIPPERDOC" and (s[0]["linked"], s[0]["unmatched"]) == (1, 3)
    assert "all 4 pages" in s[0]["detail"] and "House (4239079/26)" in s[0]["detail"]


def test_repeat_of_a_linked_document_or_plain_unmatched_is_not_a_split():
    assert split_documents([P("House (X)", [("INVOICE", 2)], [("INVOICE", 2)])]) == []          # same pages repeated
    assert split_documents([P("House (X)", [("HBL", 1)], [("SHIPPERDOC", 3)])]) == []            # unmatched only: other checks
    assert split_documents([P("House (X)", [("HBL", 1)])]) == []
