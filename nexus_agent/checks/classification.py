"""Checks that Master, House, Invoice and Shipper documents are classified in Nexus."""
from __future__ import annotations


def _canonical(label: str, types: dict) -> str | None:
    norm = (label or "").strip().lower()
    for canon, spec in types.items():
        if norm in (l.lower() for l in spec.get("labels", [])):
            return canon
    return None


def check_classification(documents: list[dict], rules: dict,
                         expected_count: int | None = None) -> tuple[bool, list[str], dict]:
    """documents: [{"name": "...pdf", "type": "<label shown in Nexus>"}]

    Returns (ok, issues, counts_by_type). Warnings (other unclassified files) are
    returned in issues prefixed with 'WARN:' and do not fail the check.
    """
    drules = rules["documents"]
    types = drules["types"]
    unclassified = {u.lower() for u in drules.get("unclassified_labels", [])}

    counts = {canon: 0 for canon in types}
    issues: list[str] = []
    for doc in documents:
        label = (doc.get("type") or "").strip()
        canon = _canonical(label, types)
        doc["canonical"] = canon
        if canon:
            counts[canon] += 1
        elif label.lower() in unclassified:
            issues.append(f"WARN: '{doc.get('name')}' is unclassified")
        else:
            issues.append(f"WARN: '{doc.get('name')}' has unmapped type '{label}'")

    for canon, spec in types.items():
        n, lo, hi = counts[canon], spec.get("min", 0), spec.get("max")
        if n < lo:
            issues.append(f"Missing {canon} document (found {n}, need at least {lo})")
        if hi is not None and n > hi:
            issues.append(f"Too many {canon} documents (found {n}, max {hi})")

    if drules.get("check_attachment_count") and expected_count is not None \
            and len(documents) < expected_count:
        issues.append(f"Nexus shows {len(documents)} documents but {expected_count} attachments were forwarded")

    ok = not any(not i.startswith("WARN:") for i in issues)
    return ok, issues, counts
