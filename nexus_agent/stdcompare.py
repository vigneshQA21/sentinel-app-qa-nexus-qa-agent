"""The standard way every data check (Air and Sea, Master / House / documents) classifies a field, document <-> Nexus shipment data.

The document is the truth: a value it prints for a field Nexus holds must be in the Nexus shipment data.
  MATCH            both have it and it is the same
  MISSING          the document prints it, Nexus is empty                      -> review
  MISMATCH         both have a value and they differ                           -> review
  NOT IN DOCUMENT  Nexus holds a value the document does not print            -> review
  HELD BY NEXUS    an ID / status Nexus assigns itself: no document value
  NOT VERIFIABLE   the document value could not be read (scan, no text layer): never a pass
  KNOWN            already logged or accepted as not a bug
  NOTHING PRINTED  empty in Nexus and nothing on the document either
Derived from the check's own row ({result, expected_from_document, shown_in_nexus, note}); a check never has to know the names."""
from __future__ import annotations

MATCH, MISSING, MISMATCH, NOT_IN_DOC = "MATCH", "MISSING", "MISMATCH", "NOT IN DOCUMENT"
HELD, NOT_VERIFIABLE, KNOWN, NOTHING, INFO = "HELD BY NEXUS", "NOT VERIFIABLE", "KNOWN", "NOTHING PRINTED", "INFO"
REVIEWABLE = (MISSING, MISMATCH, NOT_IN_DOC)


def classify(r: dict) -> str:
    res = (r.get("result") or "").upper()
    doc = (r.get("expected_from_document") or r.get("doc") or "").strip()
    nex = (r.get("shown_in_nexus") or r.get("nexus") or "").strip()
    note = (r.get("note") or "").lower()
    if res == "PASS":
        return MATCH
    if res == "KNOWN":
        return KNOWN
    if res == "NOT_VERIFIABLE":
        return NOT_VERIFIABLE
    if res == "INFO":
        if "assigned or held" in note:
            return HELD
        if "nothing to compare" in note and not nex:
            return NOTHING
        return INFO
    if res in ("FAIL", "REVIEW"):
        if not nex:
            return MISSING                                              # the document prints it, Nexus shows nothing
        if (not doc or doc.startswith("(")) and ("prints no" in note or "cannot be confirmed" in note or "could not be read" in note):
            return NOT_IN_DOC
        return MISMATCH
    return INFO


def nature(cls: str) -> str:
    """The bucket the bug-pattern statistics use: a missing value or a differing one."""
    return "missing" if cls == MISSING else "mismatch"


PASS_B, FAIL_B, DISCUSS_B, KNOWN_B, INFO_B = "PASS", "FAIL", "DISCUSSION NEEDED", "KNOWN", "INFO"


def triage(cls: str, regressed: bool = False) -> str:
    """The report bucket of one field. PASS = matches. FAIL = it matched in an earlier run and does not now (it worked, it stopped working).
    DISCUSSION NEEDED = a mismatch, a missing value, a value not printed on the document, or one that could not be verified, with no earlier pass to
    compare with: a doubt to decide together. Neither FAIL nor DISCUSSION is a bug until the user confirms it."""
    if cls == MATCH:
        return PASS_B
    if cls == KNOWN:
        return KNOWN_B
    if cls in REVIEWABLE or cls == NOT_VERIFIABLE:
        return FAIL_B if regressed else DISCUSS_B
    return INFO_B
