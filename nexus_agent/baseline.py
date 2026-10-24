"""Known-issue baseline: a finding that is already logged in the bug sheet (LOGGED / APPROVED) or was marked 'not a bug'
stays visible as KNOWN but no longer fails the case. Only NEW differences fail, and a bug whose field now passes is reported
as possibly FIXED. The baseline is the bugs table in state/agent.db, matched by the same fingerprint the bug flow uses."""
from __future__ import annotations

from .bugs import fingerprint
from .store import Store

DECIDED = ("LOGGED", "APPROVED", "NOT_A_BUG")
LABEL = {"LOGGED": "logged in the bug sheet", "APPROVED": "confirmed, waiting to be pasted", "NOT_A_BUG": "accepted, not a bug"}


def _known(store: Store) -> dict[str, str]:
    return {r["fingerprint"]: s for s in DECIDED for r in store.bugs_by_status(s)}


def apply_checks(store: Store, results: list[dict], title: str) -> tuple[int, list[str]]:
    """Master / House / document results: FAIL or REVIEW rows already decided become KNOWN; the verdict is recomputed.
    Returns (known rows, 'possibly fixed' messages)."""
    known, fixed, n = _known(store), [], 0
    for r in results:
        rows = r.get("rows") or []
        for x in rows:
            if x["result"] not in ("FAIL", "REVIEW"):
                continue
            exp, shown = " ".join(x["expected_from_document"].split()), " ".join(x["shown_in_nexus"].split())
            fp = fingerprint(r["case_id"], title, x["field"], exp, shown)
            store.history_add(fp, r.get("ipa", ""), r["case_id"], title, x["field"])
            st = known.get(fp)
            if st:
                x["note"] = f"KNOWN ISSUE ({LABEL[st]})" + (f"; {x['note']}" if x.get("note") else "")
                x["result"] = "KNOWN"
                n += 1
        if rows and r.get("verdict") in ("PASS", "FAIL"):
            r["verdict"] = "FAIL" if any(x["result"] == "FAIL" for x in rows) else "PASS"
            r["known"] = sum(1 for x in rows if x["result"] == "KNOWN")
        fixed += _fixed(store, r, title, rows)
    return n, fixed


def _fixed(store: Store, r: dict, title: str, rows: list[dict]) -> list[str]:
    import json
    out = []
    passing = {x["field"] for x in rows if x["result"] == "PASS"}
    for rec in store.bugs_by_status("LOGGED"):
        if rec["case_id"] == r["case_id"] and rec["document"] == title and rec["field"] in passing:
            c = json.loads(rec["data"])
            if c.get("ipa") == r.get("ipa") or not r.get("ipa"):
                out.append(f"{r['case_id']} {title} · {rec['field']} now matches the document: bug possibly FIXED")
    return out


def apply_mapping(store: Store, rows: list[dict]) -> int:
    """`validate` rows: when every failing part is a decided issue, the case's mapping verdict becomes PASS."""
    known, n = _known(store), 0
    for r in rows:
        if r.get("verdict") != "FAIL":
            continue
        parts = (r.get("details") or "").split(" | ")
        bad = [p for p in parts if ": FAIL" in p]
        if not bad or r.get("nexus_status") == "NOT_RECEIVED":
            continue
        fps = [fingerprint(r["case_id"], "Mapping", p.split(":")[0], "", p) for p in bad]
        for fp, p in zip(fps, bad):
            store.history_add(fp, r.get("ipa", ""), r["case_id"], "Mapping", p.split(":")[0])
        marked = [fp in known for fp in fps]
        if all(marked):
            r["details"] = " | ".join(p + "  [KNOWN ISSUE]" if p in bad else p for p in parts)
            r["verdict"] = "PASS"
            n += len(bad)
    return n
