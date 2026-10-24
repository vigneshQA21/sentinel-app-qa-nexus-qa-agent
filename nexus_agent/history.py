"""Internal bug history: how many different bugs the regression found, how often each one came back, and which are still open.
An occurrence = the finding seen in one Nexus pre-alert (checking the same pre-alert again does not count twice)."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict

from .store import Store


def backfill(store: Store) -> int:
    """Bugs saved before the history existed get their first occurrence from the stored candidate."""
    n = 0
    for st in ("PENDING", "APPROVED", "LOGGED", "NOT_A_BUG"):
        for r in store.bugs_by_status(st):
            try:
                ipa = json.loads(r["data"]).get("ipa", "")
            except Exception:
                ipa = ""
            n += store.history_add(r["fingerprint"], ipa, r["case_id"], r["document"], r["field"])
    return n


def build(store: Store) -> dict:
    backfill(store)
    bugs = {}
    for st in ("PENDING", "APPROVED", "LOGGED", "NOT_A_BUG"):
        for r in store.bugs_by_status(st):
            bugs[r["fingerprint"]] = r
    per = defaultdict(list)
    for h in store.history_rows():
        per[h["fingerprint"]].append(h)
    items = []
    for fp, occ in per.items():
        b = bugs.get(fp, {})
        m = re.search(r"!A(\d+):", b.get("note") or "")
        items.append({"fingerprint": fp, "case_id": occ[0]["case_id"], "document": occ[0]["document"], "field": occ[0]["field"],
                      "count": len(occ), "pre_alerts": [o["ipa"] for o in occ], "first": occ[0]["seen_at"][:10], "last": occ[-1]["seen_at"][:10],
                      "status": b.get("status", "?"), "sheet_row": m.group(1) if m else ""})
    items.sort(key=lambda i: (-i["count"], i["case_id"], i["document"]))
    return {"items": items, "occurrences": sum(i["count"] for i in items),
            "by_case": Counter(i["case_id"] for i in items), "by_status": Counter(i["status"] for i in items),
            "by_day": Counter(o["seen_at"][:10] for occ in per.values() for o in occ)}


def report(store: Store) -> str:
    d = build(store)
    items = d["items"]
    rep = [i for i in items if i["count"] > 1]
    lines = ["BUG HISTORY (internal tracker)", "",
             f"  Different bugs found by the regression : {len(items)}",
             f"  Occurrences in total (one per pre-alert): {d['occurrences']}",
             f"  Bugs that came back (seen in 2+ pre-alerts): {len(rep)}",
             "  By status      : " + ", ".join(f"{k} {v}" for k, v in sorted(d["by_status"].items())),
             "  By test case   : " + ", ".join(f"{k} {v}" for k, v in sorted(d["by_case"].items())),
             "  Found per day  : " + ", ".join(f"{k} {v}" for k, v in sorted(d["by_day"].items())), ""]
    if rep:
        lines.append("REPEATING BUGS (most often first)")
        for i in rep:
            lines.append(f"  x{i['count']}  {i['case_id']} · {i['document']} · {i['field']}   [{i['status']}"
                         + (f", sheet row {i['sheet_row']}" if i["sheet_row"] else "") + f"]   first {i['first']}, last {i['last']}")
            lines.append("        seen in: " + ", ".join(i["pre_alerts"]))
        lines.append("")
    lines.append("ALL BUGS")
    for i in items:
        lines.append(f"  x{i['count']}  {i['case_id']:8} {i['document']:16} {i['field'][:42]:42} {i['status']:10}"
                     + (f" row {i['sheet_row']}" if i["sheet_row"] else ""))
    return "\n".join(lines)
