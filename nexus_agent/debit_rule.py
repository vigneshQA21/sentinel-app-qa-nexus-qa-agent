"""Agent debit note rule (Japan, user 26 Nov 2026): a document titled INVOICE that has a LOGISTEED party on it (LOGISTEED EXPRESS, LOGISTEED India ...), or that starts with
LOGISTEED, is a Debit Note and belongs to the Master, whatever its printed title says.

  * SEA-JPN-002 p5  "INVOICE ... BILL to: LOGISTEED EXPRESS, LTD"      (SERPA LOGISTICA)    -> Debit Note -> Master
  * SEA-JPN-005 p4  "INVOICE ... Messrs: LOGISTEED EXPRESS, LTD."      (MORIKAWA EXPRESS)   -> Debit Note -> Master
  * SEA-JPN-008 p2-4 "LOGISTEED EXPRESS LTD ... INVOICE Number 3014590" (Airlog Group OY)    -> Debit Note -> Master
  * SEA-JPN-001 p4  "INVOICE ... Messrs. CONTEC CO.,LTD."              (the shipper's commercial invoice) -> stays Invoice -> House

Nexus does not implement this yet: it shows these as Invoice under the House. Until it does, that is reported as KNOWN
("Nexus feature not implemented"), not FAIL; `validation.agent_debit_note_gap: fail` turns it into a FAIL once Nexus has the feature.
The names come from the tenant config (`pdf_split_sea.agent_bill_to` anywhere on the page, `agent_bill_starts` at the start);
empty lists switch the rule off."""
from __future__ import annotations

import re

HEAD_LINES = 20                                     # the title and the addressee block are at the top of the first page
TITLE = re.compile(r"^\s*INVOICE\s*$", re.I)        # a title line: INVOICE alone (not 'invoice issuance', not 'INVOICE of')
OTHER_TITLE = re.compile(r"\b(?:DEBIT|CREDIT)\s+NOTE\b|\bPACKING\s+LIST\b|\bMANIFEST\b", re.I)


def _head(text: str) -> list[str]:
    return [l for l in (text or "").splitlines() if l.strip()][:HEAD_LINES]


def is_agent_bill(text: str, billed_to: list[str] | tuple[str, ...], starts: list[str] | tuple[str, ...] = ()) -> bool:
    """True when the page is titled INVOICE (title in the top lines) and either names one of `billed_to` anywhere on the page
    (LOGISTEED EXPRESS) or starts with one of `starts` (LOGISTEED: a LOGISTEED company's own invoice) - user, 26-Nov-2026.
    Layout text keeps the title on its own line; a plain-text page may glue it to the next words, so 'INVOICE' followed by
    No / Number / Reference / # also counts as a title."""
    names = [n.upper() for n in (billed_to or []) if n]
    starts_ = [n.upper() for n in (starts or []) if n]
    head = _head(text)
    if not (names or starts_) or not head:
        return False
    if OTHER_TITLE.search(" ".join(head)):
        return False
    titled = any(TITLE.match(l) for l in head) or re.search(r"(?:^|\s{2,}|\n)INVOICE\s+(?:NO\b|NUMBER\b|REFERENCE\b|#)", "\n".join(head), re.I)
    if not titled:
        return False
    flat = " ".join(re.sub(r"[^A-Z ]", " ", (text or "").upper()).split())
    first = " ".join(re.sub(r"[^A-Z ]", " ", head[0].upper()).split())
    return any(" ".join(n.split()) in flat for n in names) or any(first.startswith(" ".join(n.split())) for n in starts_)


def _rule(cfg) -> tuple[list[str], list[str]]:
    sea = cfg.settings.get("pdf_split_sea") or {}
    return sea.get("agent_bill_to") or [], sea.get("agent_bill_starts") or []


def sample_has_agent_bill(cfg, case) -> bool:
    """The case's sample has an agent's INVOICE billed to LOGISTEED EXPRESS (a page titled DEBIT NOTE does not count)."""
    billed_to, starts = _rule(cfg)
    if not (billed_to or starts):
        return False
    from .pdf_split import page_texts_layout
    from .testsuite import sample_files
    for f in [x for x in sample_files(cfg, case) if x.suffix.lower() == ".pdf"]:
        try:
            if any(is_agent_bill(t, billed_to, starts) for t in page_texts_layout(f.read_bytes(), ocr=False)):
                return True
        except Exception:
            continue
    return False


def gap_result(cfg_validation: dict) -> str:
    """Verdict for 'agent debit note shown as Invoice' while Nexus lacks the feature: KNOWN (default) or FAIL."""
    return "FAIL" if str((cfg_validation or {}).get("agent_debit_note_gap", "known")).lower() == "fail" else "KNOWN"


GAP_NOTE = ("Nexus feature not implemented yet: an invoice with a LOGISTEED party on it is a Debit Note and belongs to the "
            "Master (rule 26-Nov-2026; Japan bug sheet Sl 19, Enhancement); Nexus classifies it as Invoice under the House")
