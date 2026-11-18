"""Today's run compared with the previous days' runs (standing rule): per case, against the last earlier day that has data for it.

Reads only the stored reports (runs/_reports/validate_*.csv and the *_data_*.csv field checks), so it needs no Nexus session.
For every case it says what the mapping check did before and now, and for every field: NEW (reported now, not before), FIXED (reported before, matches
now), STILL (reported both days; `changed` when the Nexus value is not the same), REGRESSED (matched before, reported now).
The Sea checker names party blocks by the viewer heading since 13-Nov-2026: Sea findings of earlier days are not strictly comparable, and the
result says so."""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

DATA_FILES = {"Master": "master_data", "House": "house_data", "Manifest": "manifest_data", "Invoice": "invoice_data",
              "Packing List": "packing_data", "Debit Note": "debitnote_data", "Shipper Document": "shipperdoc_data"}
BAD = ("FAIL", "REVIEW")
WORST = {"FAIL": 0, "REVIEW": 1, "KNOWN": 2, "NOT_VERIFIABLE": 3, "INFO": 4, "PASS": 5}
CHECKER_CHANGE_DAY = "20261113"          # Sea party blocks named by the viewer heading, document values shown (see docs/PROGRESS_LOG.md 13-Nov)


def _rows(path: Path) -> list[dict]:
    try:
        with open(path, newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _stamp(path: Path) -> str:
    m = re.search(r"_(\d{8}_\d{6})\.csv$", path.name)
    return m.group(1) if m else ""


def days_available(reports: Path) -> list[str]:
    return sorted({m.group(1) for f in reports.glob("validate_*.csv") if (m := re.search(r"_(\d{8})_\d{6}\.csv$", f.name))})


def _is_sea(case_id: str) -> bool:
    return case_id.upper().startswith("SEA-")


def day_data(reports: Path, day: str) -> dict[str, dict]:
    """{case: {ipa, mapping, details, fields: {(document, field): row}}} for one day (yyyymmdd): the newest check per case."""
    cases: dict[str, dict] = {}
    for f in sorted(reports.glob(f"validate_{day}_*.csv"), key=_stamp):
        for r in _rows(f):
            if r.get("nexus_status") == "CREATED_IN_NEXUS" and r.get("case_id"):
                cases[r["case_id"]] = {"ipa": r.get("ipa", ""), "mapping": r.get("verdict", ""), "details": r.get("details", ""), "fields": {}}
    for doc, prefix in DATA_FILES.items():
        for f in sorted(reports.glob(f"{prefix}_{day}_*.csv"), key=_stamp):
            for r in _rows(f):
                c = cases.get(r.get("case_id", ""))
                if c is None or r.get("ipa") != c["ipa"]:
                    continue
                key = (doc, r.get("field", ""))
                old = c["fields"].get(key)
                # a field name can repeat (a party block twice): keep the worst result of the newest check of this file
                if old is None or old.get("_file") != f.name or WORST.get(r["result"], 9) < WORST.get(old["result"], 9):
                    c["fields"][key] = {**r, "_file": f.name}
    return cases


def _pretty(day: str) -> str:
    return f"{day[6:8]}-{['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][int(day[4:6])]}-{day[:4]}"


def compare_case(case_id: str, now: dict, before: dict, prev_day: str, day: str) -> dict:
    changes = []
    keys = set(now["fields"]) | set(before["fields"])
    for k in keys:
        a, b = before["fields"].get(k), now["fields"].get(k)
        ra, rb = (a or {}).get("result", ""), (b or {}).get("result", "")
        bad_a, bad_b = ra in BAD, rb in BAD
        if bad_b and not bad_a:
            kind = "REGRESSED" if ra == "PASS" else "NEW"
        elif bad_a and rb == "PASS":
            kind = "FIXED"
        elif bad_a and bad_b:
            kind = "STILL"
        else:
            continue
        ref = b or a
        changes.append({"document": k[0], "field": k[1], "kind": kind, "before": ra or "(not checked)", "after": rb or "(not checked)",
                        "document_says": (b or a or {}).get("expected_from_document", ""), "nexus_before": (a or {}).get("shown_in_nexus", ""),
                        "nexus_now": (b or {}).get("shown_in_nexus", ""), "note": (ref or {}).get("note", ""),
                        "changed": bool(a and b and (a.get("shown_in_nexus", "") != b.get("shown_in_nexus", "")))})
    order = {"REGRESSED": 0, "NEW": 1, "STILL": 2, "FIXED": 3}
    changes.sort(key=lambda c: (order[c["kind"]], c["document"], c["field"]))
    counts = defaultdict(int)
    for c in changes:
        counts[c["kind"]] += 1
    not_comparable = _is_sea(case_id) and prev_day < CHECKER_CHANGE_DAY <= day
    return {"case_id": case_id, "prev_day": prev_day, "prev_ipa": before["ipa"], "ipa": now["ipa"],
            "mapping_before": before["mapping"], "mapping_now": now["mapping"], "changes": changes, "counts": dict(counts),
            "checked_before": len(before["fields"]), "checked_now": len(now["fields"]), "not_comparable": not_comparable}


def compare(reports: Path, day: str, cases: list[str] | None = None) -> dict:
    """{day, cases: [per-case result], first_runs: [cases with no earlier day]} for `day` (yyyymmdd) against each case's last earlier day."""
    days = days_available(reports)
    now = day_data(reports, day)
    earlier = [d for d in days if d < day]
    cache: dict[str, dict] = {}
    out, first = [], []
    for cid in sorted(now):
        if cases and cid not in cases:
            continue
        prev = None
        for d in reversed(earlier):
            data = cache.setdefault(d, day_data(reports, d))
            if cid in data:
                prev = d
                break
        if prev is None:
            first.append(cid)
            continue
        out.append(compare_case(cid, now[cid], cache[prev][cid], prev, day))
    return {"day": day, "cases": out, "first_runs": first}


def render(result: dict, limit: int = 8) -> list[str]:
    """Text lines for the run report / the `./nx compare` command."""
    lines: list[str] = []
    for c in result["cases"]:
        n = c["counts"]
        head = (f"{c['case_id']}: vs {_pretty(c['prev_day'])} ({c['prev_ipa']} -> {c['ipa']}): mapping {c['mapping_before'] or '-'} -> {c['mapping_now'] or '-'}; "
                f"fields reported: {n.get('NEW', 0)} new, {n.get('REGRESSED', 0)} regressed, {n.get('STILL', 0)} still there, {n.get('FIXED', 0)} no longer reported")
        lines.append(head)
        if c["not_comparable"]:
            lines.append("    note: the Sea checker changed on 13-Nov (party blocks named by the viewer heading, document values shown): findings of the earlier day are not strictly comparable")
        for ch in [x for x in c["changes"] if x["kind"] in ("REGRESSED", "NEW", "FIXED")][:limit]:
            lines.append(f"    {ch['kind']:9} {ch['document']} · {ch['field']}: {ch['before']} -> {ch['after']}" + (f"  (Nexus now: {ch['nexus_now'][:50]})" if ch["nexus_now"] else ""))
    if result["first_runs"]:
        lines.append("No earlier run to compare with: " + ", ".join(result["first_runs"]))
    return lines or ["Nothing to compare for this day."]
