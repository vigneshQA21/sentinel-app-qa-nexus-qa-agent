"""Golden Regression gate: a new run's reports compared with the frozen baseline in <runs>/golden/ (approved 25 Nov 2026).

Reads only CSV reports (no Nexus, no Gmail). The baseline is never changed here: its files are checked against the SHA-256 sums in
manifest.json before use, and a changed or missing file stops the gate.

Per Golden case, against its baseline day (manifest `cases`):
  REGRESSION   passed in the baseline, does not pass now (mapping, a field, an AMF draft check or a Direct BL point)   -> gate FAIL
  NOT CHECKED  passed in the baseline, absent from the new run (a skipped field is never a silent pass)              -> gate FAIL
  MISSING      the case has no result in the new run at all                                                           -> gate FAIL
  ENVIRONMENT  not received in Nexus, or the read failed (ERROR): re-run it, it is not a pass                       -> gate INCOMPLETE
  IMPROVED     failed in the baseline, passes now (possibly fixed: for you to confirm)
  KNOWN        failed in the baseline and still fails
  NEW FINDING  a FAIL / REVIEW on something the baseline did not check (to review, does not block)
Verdict: FAIL if any REGRESSION / NOT CHECKED / MISSING, else INCOMPLETE if any ENVIRONMENT, else PASS."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

from . import daycompare as DC

EXTRA = {"AMF drafts": ("drafts_data", "check"), "Direct BL": ("directbl_data", "field")}   # reports outside daycompare: (file prefix, key column)
BLOCKING = ("REGRESSION", "NOT CHECKED", "MISSING")
ORDER = {"REGRESSION": 0, "NOT CHECKED": 1, "MISSING": 2, "ENVIRONMENT": 3, "NEW FINDING": 4, "IMPROVED": 5, "KNOWN": 6}


class GoldenError(RuntimeError):
    """The frozen baseline is missing or was changed: the gate cannot run."""


def load_manifest(golden: Path) -> dict:
    mf = golden / "manifest.json"
    if not mf.exists():
        raise GoldenError(f"no Golden baseline: {mf} not found")
    m = json.loads(mf.read_text(encoding="utf-8"))
    bad = [rel for rel, sha in m.get("files_sha256", {}).items()
           if not (golden / rel).exists() or hashlib.sha256((golden / rel).read_bytes()).hexdigest() != sha]
    if bad:
        raise GoldenError(f"the Golden baseline was changed or is incomplete ({len(bad)} file(s), e.g. {bad[0]}): restore it before running the gate")
    return m


def _day_key(day: str) -> str:
    return day.replace("-", "")


def _status(reports: Path, day: str, case_id: str) -> str:
    """The newest Nexus status of the case's mapping check that day ('' when it was not run)."""
    status = ""
    for f in sorted(reports.glob(f"validate_{day}_*.csv"), key=DC._stamp):
        for r in DC._rows(f):
            if r.get("case_id") == case_id:
                status = r.get("nexus_status", "") or status
    return status


def _extra(reports: Path, day: str, case_id: str) -> dict:
    """{(label, key): row} from the AMF drafts and Direct BL reports of that day: the newest file that holds the case."""
    out: dict = {}
    for label, (prefix, col) in EXTRA.items():
        for f in sorted(reports.glob(f"{prefix}_{day}_*.csv"), key=DC._stamp, reverse=True):
            rows = [r for r in DC._rows(f) if r.get("case_id") == case_id]
            if rows:
                for r in rows:
                    key = (label, (r.get("section", "") + " · " if r.get("section") else "") + r.get(col, ""))
                    old = out.get(key)
                    if old is None or DC.WORST.get(r.get("result", ""), 9) < DC.WORST.get(old.get("result", ""), 9):
                        out[key] = r
                break
    return out


def case_data(reports: Path, day: str, case_id: str) -> dict | None:
    """{status, ipa, mapping, fields} of a case on one day, or None when nothing was recorded for it."""
    base = DC.day_data(reports, day).get(case_id)
    extra = _extra(reports, day, case_id)
    status = _status(reports, day, case_id)
    if base is None and not extra and not status:
        return None
    data = base or {"ipa": next((r.get("ipa", "") for r in extra.values()), ""), "mapping": "", "details": "", "fields": {}}
    return {**data, "status": status or ("CHECKED" if extra else ""), "fields": {**data["fields"], **extra}}


def _row(case_id, b_day, r_day, kind, doc="", field="", before="", after="", says="", now="", note="") -> dict:
    return {"case_id": case_id, "baseline_day": b_day, "run_day": r_day, "kind": kind, "document": doc, "field": field, "before": before,
            "after": after, "document_says": says, "nexus_now": now, "note": note}


def compare_case(case_id: str, base: dict, new: dict | None, b_day: str, r_day: str, known_fail: dict) -> list[dict]:
    if new is None:
        return [_row(case_id, b_day, r_day, "MISSING", note="no result for this case in the new run")]
    if new.get("status") == "NOT_RECEIVED":
        return [_row(case_id, b_day, r_day, "ENVIRONMENT", "Mapping", "pre-alert", base.get("mapping", ""), "NOT_RECEIVED",
                     note="not in Nexus within the wait: re-run the case")]
    out = []
    mb, mn = base.get("mapping", ""), new.get("mapping", "")
    if mb == "PASS" and mn != "PASS":
        out.append(_row(case_id, b_day, r_day, "REGRESSION", "Mapping", "verdict", mb, mn or "(not checked)", note=new.get("details", "")[:200]))
    elif mb and mb != "PASS" and mn == "PASS":
        out.append(_row(case_id, b_day, r_day, "IMPROVED", "Mapping", "verdict", mb, mn))
    elif mb and mb != "PASS" and mn and mn != "PASS" and case_id not in known_fail:
        out.append(_row(case_id, b_day, r_day, "KNOWN", "Mapping", "verdict", mb, mn))
    for key in sorted(set(base["fields"]) | set(new["fields"])):
        a, b = base["fields"].get(key), new["fields"].get(key)
        ra, rb = (a or {}).get("result", ""), (b or {}).get("result", "")
        says, now, note = (b or a or {}).get("expected_from_document", "") or (b or a or {}).get("expected", ""), \
            (b or {}).get("shown_in_nexus", "") or (b or {}).get("actual", ""), (b or a or {}).get("note", "")
        if rb == "ERROR" and ra != "ERROR":
            kind = "ENVIRONMENT"
        elif ra == "PASS" and b is None:
            kind = "NOT CHECKED"
        elif ra == "PASS" and rb != "PASS":
            kind = "REGRESSION"
        elif ra in DC.BAD + ("NOT_VERIFIABLE", "KNOWN") and rb == "PASS":
            kind = "IMPROVED"
        elif ra in DC.BAD and rb in DC.BAD:
            kind = "KNOWN"
        elif a is None and rb in DC.BAD:
            kind = "NEW FINDING"
        else:
            continue
        out.append(_row(case_id, b_day, r_day, kind, key[0], key[1], ra or "(not checked)", rb or "(not checked)", says, now, note))
    return out


def run(runs_dir: Path, days: list[str], cases: list[str] | None = None) -> dict:
    """Compare the newest result of each Golden case among `days` (yyyy-mm-dd or yyyymmdd) with its frozen baseline."""
    golden, reports = runs_dir / "golden", runs_dir / "_reports"
    m = load_manifest(golden)
    known_fail = m.get("known_expected_fail", {})
    rows, per_case = [], {}
    wanted = [c for c in m["cases"] if not cases or c in cases]
    unknown = [c for c in (cases or []) if c not in m["cases"]]
    for cid in wanted:
        b_day = m["cases"][cid]
        base = case_data(golden / b_day, _day_key(b_day), cid)
        if base is None:
            raise GoldenError(f"the Golden baseline has no result for {cid} on {b_day}")
        new, r_day = None, ""
        for d in sorted(days, key=_day_key, reverse=True):                 # the newest given day that has the case
            new = case_data(reports, _day_key(d), cid)
            if new is not None:
                r_day = d
                break
        found = compare_case(cid, base, new, b_day, r_day, known_fail)
        rows += found
        kinds = {r["kind"] for r in found}
        per_case[cid] = "FAIL" if kinds & set(BLOCKING) else "INCOMPLETE" if "ENVIRONMENT" in kinds else "PASS"
    rows.sort(key=lambda r: (ORDER[r["kind"]], r["case_id"], r["document"], r["field"]))
    verdicts = set(per_case.values())
    verdict = "FAIL" if "FAIL" in verdicts else "INCOMPLETE" if "INCOMPLETE" in verdicts else "PASS"
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in ORDER}
    return {"verdict": verdict, "per_case": per_case, "rows": rows, "counts": counts, "days": days, "unknown_cases": unknown,
            "frozen_on": m.get("frozen_on", ""), "tenant": m.get("tenant", "")}


def write_report(runs_dir: Path, result: dict) -> Path:
    out = runs_dir / "_reports" / f"golden_{datetime.now():%Y%m%d_%H%M%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["case_id", "baseline_day", "run_day", "kind", "document", "field", "before", "after", "document_says", "nexus_now", "note"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(result["rows"])
    return out


def render(result: dict, limit: int = 40) -> list[str]:
    c = result["counts"]
    lines = [f"GOLDEN GATE: {result['verdict']}   (tenant {result['tenant'] or '-'}, baseline frozen {result['frozen_on']}, run day(s) {', '.join(result['days'])})",
             f"  cases: " + ", ".join(f"{k} {v}" for k, v in sorted(result["per_case"].items())),
             "  " + ", ".join(f"{k.lower()} {n}" for k, n in c.items())]
    if result["unknown_cases"]:
        lines.append("  not Golden cases (ignored): " + ", ".join(result["unknown_cases"]))
    for r in [x for x in result["rows"] if x["kind"] not in ("KNOWN",)][:limit]:
        lines.append(f"  {r['kind']:12} {r['case_id']:12} {r['document']} · {r['field']}: {r['before']} -> {r['after']}"
                     + (f"  (Nexus now: {r['nexus_now'][:50]})" if r["nexus_now"] else "") + (f"  [{r['note'][:80]}]" if r["note"] and r["kind"] in ("MISSING", "ENVIRONMENT") else ""))
    return lines
