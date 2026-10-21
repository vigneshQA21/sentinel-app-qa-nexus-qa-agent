"""Shipper data validation, automatic fixes and per-shipment corrections."""
from __future__ import annotations

import re
from pathlib import Path

import yaml


def mawb_check_digit_ok(mawb: str) -> bool:
    digits = re.sub(r"\D", "", mawb or "")
    if len(digits) != 11:
        return False
    return int(digits[3:10]) % 7 == int(digits[10])


def _autofix(value: str, ops: list[str]) -> str:
    v = value if isinstance(value, str) else ("" if value is None else str(value))
    if "trim" in ops:
        v = v.strip()
    if "collapse_spaces" in ops:
        v = re.sub(r"\s+", " ", v)
    if "upper" in ops:
        v = v.upper()
    if "mawb_dash" in ops:
        d = re.sub(r"\D", "", v)
        if len(d) == 11:
            v = f"{d[:3]}-{d[3:]}"
    return v


def load_corrections(corrections_dir: Path, ref: str) -> dict:
    path = Path(corrections_dir) / f"{ref}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {k: ("" if v is None else str(v)) for k, v in data.items()}


def evaluate_shipper(data: dict, rules: dict, corrections: dict | None = None
                     ) -> tuple[dict, list[dict], list[str]]:
    """Returns (target_values, edits, issues).

    edits  = [{"field", "old", "new", "reason"}] that should be saved to Nexus.
    issues = rule failures that remain AFTER fixes/corrections (=> NEEDS_REVIEW).
    """
    srules = rules["shipper"]
    target = {k: ("" if v is None else str(v)) for k, v in data.items()}
    reasons: dict[str, str] = {}

    # 1. automatic fixes
    per_field: dict[str, list[str]] = {}
    for op, fields in (srules.get("autofix") or {}).items():
        for f in fields:
            per_field.setdefault(f, []).append(op)
    for f, ops in per_field.items():
        if f in target:
            fixed = _autofix(target[f], ops)
            if fixed != target[f]:
                target[f] = fixed
                reasons[f] = "autofix: " + ",".join(ops)

    # 2. operator corrections win over everything
    for f, v in (corrections or {}).items():
        if target.get(f) != v:
            target[f] = v
            reasons[f] = "correction file"

    # 3. validate
    issues: list[str] = []
    for f in srules.get("mandatory", []):
        if not target.get(f, "").strip():
            issues.append(f"{f} is empty")
    for f, pattern in (srules.get("patterns") or {}).items():
        v = target.get(f, "")
        if v and not re.fullmatch(pattern, v):
            issues.append(f"{f} '{v}' does not match {pattern}")
    for f in srules.get("positive_numbers", []):
        v = target.get(f, "")
        try:
            if float(v.replace(",", "")) <= 0:
                issues.append(f"{f} must be > 0 (got {v})")
        except ValueError:
            issues.append(f"{f} is not a number ('{v}')")
    if srules.get("mawb_check_digit") and target.get("mawb") and not mawb_check_digit_ok(target["mawb"]):
        issues.append(f"mawb '{target['mawb']}' fails the mod-7 check digit")

    edits = [
        {"field": f, "old": data.get(f, ""), "new": target[f], "reason": reasons[f]}
        for f in reasons if str(data.get(f, "")) != target[f]
    ]
    return target, edits, issues
