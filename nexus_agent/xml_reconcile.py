"""Compares the XML pushed to the TMS with the shipper snapshot taken before the push."""
from __future__ import annotations

import re
from datetime import datetime

from lxml import etree

_DATE_FORMATS = ["%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y%m%d", "%d %b %Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%m/%d/%Y"]


def _norm_text(v) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip().casefold()


def _norm_number(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _norm_date(v) -> str | None:
    s = str(v or "").strip()
    if not s:
        return None
    if "T" in s:  # ISO datetime: drop the timezone suffix
        s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", s)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # unknown format: compare as given


def _xml_value(root, xpath: str, ns: dict) -> str | None:
    found = root.xpath(xpath, namespaces=ns or None)
    if isinstance(found, list):
        if not found:
            return None
        found = found[0]
    if isinstance(found, etree._Element):
        return "".join(found.itertext())
    return str(found)


def reconcile(xml_text: str, snapshot: dict, mapping: dict) -> list[dict]:
    """Returns one row per mapped field: {field, expected, actual, result, required}.
    result: MATCH | MISMATCH | MISSING_IN_XML | NOT_IN_NEXUS
    """
    root = etree.fromstring(xml_text.strip().encode("utf-8"))
    ns = mapping.get("namespaces") or {}
    tol_default = float((mapping.get("defaults") or {}).get("number_tolerance", 0.01))
    rows = []
    for field, spec in mapping["fields"].items():
        expected = snapshot.get(field)
        actual = _xml_value(root, spec["xpath"], ns)
        kind = spec.get("type", "text")
        required = bool(spec.get("required", False))

        if actual is None or str(actual).strip() == "":
            result = "MISSING_IN_XML" if (required or str(expected or "").strip()) else "MATCH"
        elif expected is None:
            result = "NOT_IN_NEXUS"
        elif kind == "number":
            a, e = _norm_number(actual), _norm_number(expected)
            tol = float(spec.get("tolerance", tol_default))
            result = "MATCH" if a is not None and e is not None and abs(a - e) <= tol else "MISMATCH"
        elif kind == "date":
            result = "MATCH" if _norm_date(actual) == _norm_date(expected) else "MISMATCH"
        else:
            result = "MATCH" if _norm_text(actual) == _norm_text(expected) else "MISMATCH"

        rows.append({"field": field, "expected": expected, "actual": actual,
                     "result": result, "required": required})
    return rows


def is_clean(rows: list[dict]) -> bool:
    return all(r["result"] in ("MATCH", "NOT_IN_NEXUS") for r in rows)
