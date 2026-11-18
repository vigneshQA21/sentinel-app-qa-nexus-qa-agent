"""Air multi-house checks (MH-nnn cases): one Master, N Houses, a manifest, a duplicate House page.

The expectation is read from the source PDF itself (nothing hard-coded per sample): the HAWB numbers come from the House pages, a House
page whose text equals an earlier one is a duplicate, and the Master AWB is the number in the AWB prefix line.
`check_parents` is pure (parents as read by UatPages.read_parents + the Unresolved Documents block), so it is tested without Nexus."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config
from .pdf_split import page_texts, sea_page_labels

HAWB_RE = re.compile(r"HAWB\s*(?:NO\.?|NUMBER|#)?\s*[:：#]?\s*([A-Z0-9]*\d[A-Z0-9]*)", re.IGNORECASE)
MAWB_RE = re.compile(r"\b(\d{3})\s*[A-Z]{3}\s*(\d{8})\b")


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


@dataclass
class Expected:
    mawb: str = ""
    hawbs: list[str] = field(default_factory=list)              # unique, in page order
    pages: dict[str, list[int]] = field(default_factory=dict)   # hawb -> pages carrying it
    duplicates: dict[str, list[int]] = field(default_factory=dict)   # hawb -> pages that repeat an earlier page's text
    manifest: bool = True
    scanned_pages: list[int] = field(default_factory=list)      # pages without text (read by OCR in Nexus, not by this check)
    omitted: list[str] = field(default_factory=list)            # HAWBs of the sample this case never sends (the Manifest may still list them)


def expected_from_pdf(pdf_bytes: bytes, manifest: bool = True) -> Expected:
    texts = page_texts(pdf_bytes)
    exp = Expected(manifest=manifest)
    seen_text: dict[str, int] = {}
    for no, t in enumerate(texts, 1):
        if not t.strip():
            exp.scanned_pages.append(no)
            continue
        m = MAWB_RE.search(t)
        if m and not exp.mawb:
            exp.mawb = f"{m.group(1)}-{m.group(2)}"
        h = HAWB_RE.search(t)
        if not h:
            continue
        hawb = h.group(1).upper()
        exp.pages.setdefault(hawb, []).append(no)
        if hawb not in exp.hawbs:
            exp.hawbs.append(hawb)
        key = _norm(t)
        if key in seen_text:
            exp.duplicates.setdefault(hawb, []).append(no)
        else:
            seen_text[key] = no
    return exp


SEA_MBL_RE = re.compile(r"B/L\s*NO\.?\s*[:：]?\s*([A-Z0-9]{8,})", re.IGNORECASE)


def expected_from_sea_pdf(pdf_bytes: bytes, sea: dict) -> Expected:
    """Sea consolidated PDF: the Houses are the pages the Sea page rules label HBL (their first line is the forwarder's own bill number),
    the Master bill is the carrier's 'B/L NO.' on the pages that are not a House. No manifest is expected."""
    texts = page_texts(pdf_bytes)
    labels = sea_page_labels(texts, sea)
    house_ref = re.compile(sea["house_ref_pattern"])
    exp = Expected(manifest=False)
    seen_text: dict[str, int] = {}
    for no, (t, lab) in enumerate(zip(texts, labels), 1):
        if not t.strip():
            exp.scanned_pages.append(no)
            continue
        first = next((l.strip() for l in t.splitlines() if l.strip()), "")
        if lab == "HBL" and house_ref.match(first):
            hb = first.upper()
            exp.pages.setdefault(hb, []).append(no)
            if hb not in exp.hawbs:
                exp.hawbs.append(hb)
            key = _norm(t)
            if key in seen_text:
                exp.duplicates.setdefault(hb, []).append(no)
            else:
                seen_text[key] = no
        elif not exp.mawb:
            m = SEA_MBL_RE.search(" ".join(t.split()))
            if m and m.group(1).upper() not in exp.hawbs:
                exp.mawb = m.group(1).upper()
    return exp


@dataclass
class Check:
    name: str
    status: str            # PASS | FAIL | REVIEW | INFO
    detail: str


def _kind(p: dict) -> str:
    k = p.get("kind") or ""
    n = p.get("parent") or ""
    if k in ("Master", "House"):
        return k
    return "Manifest" if "MANIFEST" in n.upper() or k == "Manifest" else k or n


def check_parents(parents: list[dict], exp: Expected, unresolved: dict | None = None) -> list[Check]:
    """parents = [{parent, kind, linked:[{label,pages}], unmatched, unclassified}] as read in the Nexus viewer."""
    out: list[Check] = []
    masters = [p for p in parents if _kind(p) == "Master"]
    houses = [p for p in parents if _kind(p) == "House"]
    mans = [p for p in parents if _kind(p) == "Manifest"]

    out.append(Check("One Master", "PASS" if len(masters) == 1 else "FAIL", f"{len(masters)} Master parent(s) in Nexus: " + (", ".join(p["parent"] for p in masters) or "none")))
    if exp.mawb and masters:
        ok = _norm(exp.mawb) in _norm(masters[0]["parent"])
        out.append(Check("Master AWB", "PASS" if ok else "FAIL", f"document {exp.mawb} | Nexus parent '{masters[0]['parent']}'"))

    names = {p["parent"]: _norm(p["parent"]) for p in houses}
    draft = [n for n, v in names.items() if any(_norm(o) in v for o in exp.omitted)]
    n_houses = len(houses) - len(draft)                      # a draft of an omitted House is reported on its own line below
    out.append(Check("House count", "PASS" if n_houses == len(exp.hawbs) else "FAIL",
                     f"document has {len(exp.hawbs)} distinct HAWB(s) ({', '.join(exp.hawbs)}); Nexus has {len(houses)} House parent(s): " + (", ".join(p["parent"] for p in houses) or "none")))
    for h in exp.hawbs:
        hit = [n for n, v in names.items() if _norm(h) in v]
        out.append(Check(f"House {h}", "PASS" if len(hit) == 1 else "FAIL",
                         f"{'one House parent' if len(hit) == 1 else str(len(hit)) + ' House parents'} for this HAWB" + (f" ({hit[0]})" if hit else "")))
    unexpected = [n for n, v in names.items() if n not in draft and not any(_norm(h) in v for h in exp.hawbs)]
    for h in exp.omitted:                       # a House that was never sent: nothing of it may be mapped; a draft from the Manifest is only a note
        hit = [n for n in draft if _norm(h) in _norm(n)]
        out.append(Check(f"Omitted House {h}", "REVIEW" if hit else "PASS",
                         (f"Nexus has a House parent for the House that was never sent ({hit[0]}): a draft from the Manifest? check it holds no document" if hit
                          else "no House parent for the House that was never sent")))
    if unexpected:
        out.append(Check("Unexpected House", "FAIL", "House parent(s) whose number is not a HAWB of the document: " + ", ".join(unexpected)))

    if exp.manifest:
        out.append(Check("Manifest", "PASS" if len(mans) == 1 else "FAIL", f"{len(mans)} Manifest parent(s) in Nexus"))

    for h, pages in exp.duplicates.items():      # a repeated House page must not create a second House
        n = sum(1 for v in names.values() if _norm(h) in v)
        extra = len(houses) - len(exp.hawbs)                    # a repeated page may be named by another number (e.g. the Reference Number)
        out.append(Check(f"Duplicate of {h} (page {', '.join(map(str, pages))})", "PASS" if n == 1 and extra <= 0 else "FAIL",
                         f"{n} House parent(s) named {h}" + (f", but {extra} more House parent(s) than distinct HAWBs: " + ", ".join(unexpected) if extra > 0 else "") +
                         ": the repeated page must not create another House"))
        flagged = [r for r in (unresolved or {}).get("lines", []) if re.search(r"duplicate", r, re.I)]
        out.append(Check("Duplicate page flagged", "PASS" if flagged else "REVIEW",
                         ("remark in Unresolved Documents: " + "; ".join(flagged[:2])) if flagged else
                         "no 'Duplicate' remark in the Unresolved Documents table: check where the repeated page went"))

    stray = [f"{p['parent']}: {g['label']}" for p in parents for k in ("unmatched", "unclassified") for g in p.get(k, [])]
    if stray:
        out.append(Check("Unmatched / unclassified", "REVIEW", "; ".join(stray)))
    if exp.scanned_pages:
        out.append(Check("Scanned pages", "INFO", f"page(s) {', '.join(map(str, exp.scanned_pages))} have no text in the PDF (Master / manifest scans, read by Nexus OCR)"))
    return out


def verdict(checks: list[Check]) -> str:
    return "FAIL" if any(c.status == "FAIL" for c in checks) else "PASS"


def expected_for_case(cfg: Config, case_id: str) -> Expected | None:
    from .testsuite import read_extra_cases, sample_files
    from .mhphase import CASES as PHASED, expected_for as phased_expected
    if case_id in PHASED:
        return phased_expected(cfg, case_id)
    case = next((c for c in read_extra_cases(cfg) if c.id == case_id), None)
    files = sample_files(cfg, case) if case else []
    if not files:
        return None
    if case_id.upper().startswith("SEA-"):
        return expected_from_sea_pdf(files[0].read_bytes(), cfg.settings["pdf_split_sea"])
    return expected_from_pdf(files[0].read_bytes(), manifest="manifest" in (case.docs or "").lower())
