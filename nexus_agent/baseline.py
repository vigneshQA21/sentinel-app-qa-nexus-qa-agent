"""Known-issue baseline: a finding that is already logged in the bug sheet (LOGGED / APPROVED) or was marked 'not a bug'
stays visible as KNOWN but no longer fails the case. Only NEW differences fail, and a bug whose field now passes is reported
as possibly FIXED. The baseline is the bugs table in state/agent.db, matched by the same fingerprint the bug flow uses."""
from __future__ import annotations

import re

from .bugs import fingerprint
from .store import Store

DECIDED = ("LOGGED", "APPROVED", "NOT_A_BUG")
LABEL = {"LOGGED": "logged in the bug sheet", "APPROVED": "confirmed, waiting to be pasted", "NOT_A_BUG": "accepted, not a bug"}


def _known(store: Store) -> dict[str, str]:
    return {r["fingerprint"]: s for s in DECIDED for r in store.bugs_by_status(s)}


def _recheck(store: Store) -> dict[str, str]:
    """Findings accepted only because of another bug: the note starts with RECHECK and is shown on every run until that bug is fixed."""
    return {r["fingerprint"]: r["note"] for r in store.bugs_by_status("NOT_A_BUG") if (r.get("note") or "").startswith("RECHECK")}


def apply_checks(store: Store, results: list[dict], title: str) -> tuple[int, list[str]]:
    """Master / House / document results: FAIL or REVIEW rows already decided become KNOWN; the verdict is recomputed.
    Returns (known rows, 'possibly fixed' messages)."""
    known, fixed, n, recheck = _known(store), [], 0, _recheck(store)
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
                r.setdefault("reseen", []).append({"case_id": r["case_id"], "document": title, "field": x["field"], "fingerprint": fp, "status": st})
                x["note"] = (f"KNOWN ISSUE ({LABEL[st]})" + (f"; {recheck[fp][8:].strip()}" if fp in recheck else "")
                             + (f"; {x['note']}" if x.get("note") else ""))
                x["result"] = "KNOWN"
                n += 1
        if rows and r.get("verdict") in ("PASS", "FAIL"):
            r["verdict"] = "FAIL" if any(x["result"] == "FAIL" for x in rows) else "PASS"
            r["known"] = sum(1 for x in rows if x["result"] == "KNOWN")
        fixed += _fixed(store, r, title, rows)
    return n, fixed


def _where(rec: dict) -> str:
    import re
    m = re.search(r"!A(\d+):", rec.get("note") or "")
    return f" (bug sheet row {m.group(1)})" if m else ""


def reseen_lines(store: Store, results: list[dict]) -> list[str]:
    """One line per already-raised finding that came back in this run: how many pre-alerts it has now been seen in."""
    import re
    counts: dict[str, int] = {}
    for h in store.history_rows():
        counts[h["fingerprint"]] = counts.get(h["fingerprint"], 0) + 1
    out = []
    for r in results:
        for x in r.get("reseen") or []:
            rec = store.bug_get(x["fingerprint"]) or {}
            m = re.search(r"!A(\d+):|row (\d+)", rec.get("note") or "")
            tag = f"bug sheet row {m.group(1) or m.group(2)}" if m else ("not a bug" if x["status"] == "NOT_A_BUG" else x["status"].lower())
            out.append(f"  STILL THERE x{counts.get(x['fingerprint'], 1)}  {x['case_id']} · {x['document']} · {x['field']}  [{tag}]")
    return out


def _fixed(store: Store, r: dict, title: str, rows: list[dict]) -> list[str]:
    import json
    out = []
    passing = {x["field"] for x in rows if x["result"] == "PASS"}
    for rec in store.bugs_by_status("LOGGED"):
        if rec["case_id"] == r["case_id"] and rec["document"] == title and rec["field"] in passing:
            out.append(f"{r['case_id']} {title} · {rec['field']} now matches the document: bug possibly FIXED{_where(rec)}")
    return out


def apply_mapping(store: Store, rows: list[dict]) -> int:
    """`validate` rows: when every failing part is a decided issue, the case's mapping verdict becomes PASS."""
    known, n = _known(store), 0
    for r in rows:
        for p in (r.get("details") or "").split(" | "):            # a logged mapping bug whose document is now placed correctly
            if re.match(r"^[A-Z ]+: PASS", p):
                fp = fingerprint(r["case_id"], "Mapping", p.split(":")[0], "", p.split(" (")[0].replace(": PASS", ": FAIL") + " (not found in Nexus)")
                rec = store.bug_get(fp)
                if rec and rec["status"] == "LOGGED":
                    r.setdefault("fixed", []).append(f"{r['case_id']} Mapping · {p.split(':')[0]} is now placed correctly: bug possibly FIXED{_where(rec)}")
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
        for fp, p, was in zip(fps, bad, marked):
            if was:
                r.setdefault("reseen", []).append({"case_id": r["case_id"], "document": "Mapping", "field": p.split(":")[0], "fingerprint": fp,
                                                   "status": known[fp]})
        if all(marked):
            r["details"] = " | ".join(p + "  [KNOWN ISSUE]" if p in bad else p for p in parts)
            r["verdict"] = "PASS"
            n += len(bad)
    return n
