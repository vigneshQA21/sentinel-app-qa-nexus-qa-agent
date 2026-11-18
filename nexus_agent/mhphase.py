"""Air multi-house individual sends (MH-002, MH-003, MH-004): ONE consolidated sample (MH-001's FJ-0000088) is split into its documents
and sent in different orders, one phase at a time (docs/AIR_MULTI_HOUSE_PLAN.md section 4).

The split is read from the PDF itself: the Master is the first page, the Manifest is every page between it and the first House page, a House is
the page(s) carrying a HAWB, and a page that repeats an earlier House page is the duplicate (left out: MH-001 covers it).
`fill` empties samples/<case>/ and loads ONE phase with a number in front of each file name, so the suite (which sends the folder in name order)
sends them in phase order. Nothing is sent here. The same shipment cannot be in Nexus twice: the previous case's pre-alerts are deleted first."""
from __future__ import annotations

import io
import shutil
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .config import Config
from .multihouse import Expected, expected_from_pdf

SOURCE_CASE = "MH-001"
# case -> {phase: [document keys in sending order]}; keys: master, manifest, house1..houseN (houses in page order), "houses" = all houses
CASES: dict[str, dict[str, list[str]]] = {
    "MH-002": {"1": ["houses"], "2": ["master", "manifest"]},                  # REG-014: Houses before the Master
    "MH-003": {"1": ["master", "house1", "house2"], "2": ["house3"]},           # REG-015: a new House after the first processing
    "MH-004": {"1": ["master", "manifest", "house1", "house2"]},                # REG-020: the third House is never sent
}
OMITTED: dict[str, list[str]] = {"MH-004": ["house3"]}                         # documents of the sample this case never sends


def source_pdf(cfg: Config) -> Path:
    d = cfg.path(cfg.settings["testsuite"]["samples_dir"]) / SOURCE_CASE
    files = sorted(d.glob("*.pdf")) if d.is_dir() else []
    if not files:
        raise FileNotFoundError(f"{SOURCE_CASE} has no sample PDF in {d}")
    return files[0]


def split(pdf_bytes: bytes) -> tuple[dict[str, list[int]], Expected]:
    """({key: 0-based pages}, expectation). Keys: master, manifest, house1..houseN (HAWB order of the pages)."""
    exp = expected_from_pdf(pdf_bytes)
    dup_pages = {p - 1 for pages in exp.duplicates.values() for p in pages}
    house_pages = sorted(p - 1 for pages in exp.pages.values() for p in pages if p - 1 not in dup_pages)
    if not house_pages:
        raise ValueError("no House page (HAWB) found in the sample")
    parts: dict[str, list[int]] = {"master": [0]}
    if house_pages[0] > 1:
        parts["manifest"] = list(range(1, house_pages[0]))
    for n, p in enumerate(house_pages, 1):
        parts[f"house{n}"] = [p]
    return parts, exp


def _write(reader: PdfReader, pages: list[int]) -> bytes:
    w = PdfWriter()
    for i in pages:
        w.add_page(reader.pages[i])
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _label(key: str) -> str:
    return {"master": "Master", "manifest": "Manifest"}.get(key, f"House {key[5:]}" if key.startswith("house") else key)


def keys_for(case_id: str, phase: str, parts: dict[str, list[int]]) -> list[str]:
    if case_id not in CASES or phase not in CASES[case_id]:
        raise ValueError(f"{case_id}: unknown phase '{phase}' (choose {', '.join(CASES.get(case_id, {})) or 'none'})")
    out: list[str] = []
    for k in CASES[case_id][phase]:
        out += sorted(x for x in parts if x.startswith("house")) if k == "houses" else [k]
    missing = [k for k in out if k not in parts]
    if missing:
        raise ValueError(f"the sample has no {', '.join(missing)}")
    return out


def fill(cfg: Config, case_id: str, phase: str, fj: str = "FJ-0000088") -> list[Path]:
    """Empties samples/<case>/ (only this staging folder) and loads the phase. Raises ValueError / FileNotFoundError with the problem."""
    src = source_pdf(cfg)
    data = src.read_bytes()
    parts, _ = split(data)
    keys = keys_for(case_id, phase, parts)
    reader = PdfReader(io.BytesIO(data))
    dest = cfg.path(cfg.settings["testsuite"]["samples_dir"]) / case_id
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*"):
        if old.is_file():
            old.unlink()
    out = []
    for n, k in enumerate(keys, 1):
        target = dest / f"{n:02d} {fj} - {_label(k)}.pdf"
        target.write_bytes(_write(reader, parts[k]))
        out.append(target)
    return out


def expected_for(cfg: Config, case_id: str) -> Expected | None:
    """What the FINAL state of the case must look like, read from the source sample: the omitted House is not expected, the duplicate page is not sent."""
    if case_id not in CASES:
        return None
    data = source_pdf(cfg).read_bytes()
    parts, exp = split(data)
    hawb_of = {}
    for h, pages in exp.pages.items():
        for p in pages:
            hawb_of[p - 1] = h
    omitted = {hawb_of[parts[k][0]] for k in OMITTED.get(case_id, []) if k in parts}
    exp.omitted = sorted(omitted)
    exp.hawbs = [h for h in exp.hawbs if h not in omitted]
    exp.duplicates = {}                                  # the repeated page is never sent in these cases
    exp.manifest = any("manifest" in keys for keys in CASES[case_id].values())      # MH-003 sends none
    return exp
