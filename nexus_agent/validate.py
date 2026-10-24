"""End-to-end UI validation: find the pre-alert Nexus created for a test case and check that every document
was classified and mapped to the right section (Master / House), as the test case's Expected Mapping says."""
from __future__ import annotations

import csv
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import Config
from .models import PreAlert, Status
from .nexus.pages import NexusPages
from .nexus.session import NexusSession, SessionExpired
from .nexus.uat import UatPages
from .store import Store
from .testsuite import Case

log = logging.getLogger(__name__)


# --- normalising names ---------------------------------------------------------------
def canonical(text: str, aliases: dict[str, list[str]]) -> str:
    """Canonical document type for a Nexus label / document name / test-case wording ('' if unknown). Short aliases (PO) only
    match as a whole word, so 'PO' does not match 'POSTAL' or 'PORT'."""
    up = " ".join((text or "").upper().replace("_", " ").split())
    for canon, words in aliases.items():
        if up == canon:
            return canon
        for w in words:
            w = w.upper()
            if (re.search(rf"(?<![A-Z0-9]){re.escape(w)}(?![A-Z0-9])", up) if len(w) <= 3 else w in up):
                return canon
    return ""


def section_in(text: str, sections: list[str]) -> str | None:
    for sec in sections:
        if re.search(rf"\b{re.escape(sec)}\b", text or "", re.IGNORECASE):
            return sec
    return None


def parse_expected(expected_mapping: str, docs: str, cfg: Config) -> dict[str, str | None]:
    """{canonical type: expected section} for the documents of a case.
    expected_mapping looks like 'Master → Master, House → House, Manifest → Master, Invoice → House';
    docs like 'Master + House + Manifest + Invoice + Packing List'."""
    aliases = cfg.settings["validation"]["type_aliases"]
    sections = cfg.selectors["mapping"]["sections"]
    rules: dict[str, str | None] = {}
    others: str | None = None
    for part in re.split(r"[,;\n]+", expected_mapping or ""):
        m = re.match(r"\s*(.+?)\s*(?:→|->|=>)\s*(.+?)\s*$", part)
        if not m:
            continue
        left, right = m.group(1), m.group(2)
        sec = section_in(right, sections)
        if re.match(r"(other|remaining|all other)", left, re.IGNORECASE):
            others = sec
            continue
        for piece in re.split(r"\s*(?:/|&|\band\b)\s*", left, flags=re.IGNORECASE):     # 'Invoice/Packing List' = two document types
            canon = canonical(piece, aliases)
            if canon:
                rules[canon] = sec
    expected: dict[str, str | None] = {}
    for d in re.split(r"\s*\+\s*", docs or ""):
        canon = canonical(d, aliases)
        if not canon:
            continue                                   # e.g. 'random/unclassified document', 'PO'
        if canon in rules:
            expected[canon] = rules[canon]
        elif others:
            expected[canon] = others
    return expected


@dataclass
class DocResult:
    doc_type: str
    expected_section: str | None
    status: str                  # PASS | FAIL
    detail: str


@dataclass
class Verdict:
    results: list[DocResult] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)

    def passed(self, fail_on_unexpected: bool = False) -> bool:
        return all(r.status in ("PASS", "REVIEW") for r in self.results) and not (fail_on_unexpected and self.unexpected)


def compare(expected: dict[str, str | None], actual: list[dict], aliases: dict[str, list[str]],
            accept: dict[str, set[str]] | None = None, alternates: dict[str, list[str]] | None = None) -> Verdict:
    """actual = [{section, name, type}] from the Nexus page. accept = extra sections that count as correct for a
    type, e.g. {"MANIFEST": {"Manifest"}}: Nexus lists the manifest as its own parent, tied to the master."""
    accept = accept or {}
    alternates = alternates or {}
    found: dict[str, list[tuple[str, str]]] = {}
    unexpected = []
    for d in actual:
        canon = canonical(d.get("type", ""), aliases) or canonical(d.get("name", ""), aliases)
        if not canon or (canon not in expected and not any(canon in alts for k, alts in alternates.items() if k in expected)):
            unexpected.append(f"{d.get('name') or d.get('type')} in {d['section']}")
            continue
        found.setdefault(canon, []).append((d["section"], d.get("name", "")))
    v = Verdict(unexpected=unexpected)
    for canon, want in expected.items():
        have = found.get(canon, [])
        alt = [(sec, nm) for a in alternates.get(canon, []) for sec, nm in found.get(a, [])]
        if not have and alt and (want is None or any(sec == want for sec, _ in alt)):
            v.results.append(DocResult(canon, want, "REVIEW", f"Nexus shows it as another type, in {alt[0][0]}"))
        elif not have:
            v.results.append(DocResult(canon, want, "FAIL", "not found in Nexus"))
        elif want is None or any(sec == want or sec in accept.get(canon, set()) for sec, _ in have):
            where = ", ".join(sorted({sec for sec, _ in have}))
            v.results.append(DocResult(canon, want, "PASS", f"in {where}"))
        else:
            where = ", ".join(sorted({sec for sec, _ in have}))
            v.results.append(DocResult(canon, want, "FAIL", f"found in {where}, expected {want}"))
    return v


def plan_wait(elapsed_s: float | None, initial_s: float, max_s: float, explicit: float | None = None) -> tuple[float, float]:
    """(seconds to sleep as buffer, seconds to poll afterwards). elapsed_s = time since the email was sent."""
    if explicit is not None:
        return 0.0, float(explicit)
    if elapsed_s is None:
        return 0.0, float(max_s)
    sleep_s = max(0.0, initial_s - elapsed_s)
    return sleep_s, max(60.0, max_s - elapsed_s - sleep_s)


def _buffer(seconds: float, label: str) -> None:
    end = time.monotonic() + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            return
        log.info("%s: waiting %ds for Nexus to process the email before checking", label, int(left))
        time.sleep(min(30, left))


# --- the run ---------------------------------------------------------------------------
def validate_case(cfg: Config, pages, store: Store, case: Case, ref: str | None = None,
                  wait_seconds: float | None = None) -> dict:
    ref = ref or store.ref_for_case(case.id) or case.sample_ref
    row = {"case_id": case.id, "ref": ref or "", "ipa": "", "nexus_status": "", "verdict": "", "appeared_after_s": "",
           "details": "", "evidence": ""}
    if isinstance(pages, UatPages):
        return _validate_uat(cfg, pages, store, case, ref, wait_seconds, row)
    if not ref:
        row.update(nexus_status="NO_REFERENCE", verdict="ERROR",
                   details="no reference known for this case: send it first or pass --ref")
        return row
    evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    if cfg.settings["validation"].get("evidence", True):
        row["evidence"] = str(evidence)
    t = cfg.settings["timing"]
    started = datetime.now()
    wait = t["prealert_wait_seconds"] if wait_seconds is None else wait_seconds
    if not pages.wait_for_prealert(ref, wait, t["prealert_poll_seconds"]):
        if row["evidence"]:
            pages.screenshot(evidence / "not_received.png")
        store.upsert(PreAlert(ref=ref), Status.NOT_RECEIVED, f"{case.id}: not in Nexus after {int(wait)}s")
        row.update(nexus_status="NOT_RECEIVED", verdict="FAIL", details=f"{ref} not found in Nexus after {int(wait)}s")
        return row
    row["appeared_after_s"] = int((datetime.now() - started).total_seconds())
    store.upsert(PreAlert(ref=ref), Status.CREATED_IN_NEXUS, f"{case.id}: appeared after {row['appeared_after_s']}s")
    row["nexus_status"] = "CREATED_IN_NEXUS"
    if row["evidence"]:
        pages.screenshot(evidence / "list.png")
    pages.open_prealert(ref)
    actual = pages.read_mapping(evidence if row["evidence"] else None)
    expected = parse_expected(case.expected_mapping, case.docs, cfg)
    if not expected:
        row.update(verdict="ERROR", details="could not read an expected mapping from the test case")
        return row
    v = compare(expected, actual, cfg.settings["validation"]["type_aliases"])
    ok = v.passed(cfg.settings["validation"].get("fail_on_unexpected", False))
    row["verdict"] = "PASS" if ok else "FAIL"
    lines = [f"{r.doc_type}: {r.status} ({r.detail})" for r in v.results]
    if v.unexpected:
        lines.append("unexpected: " + "; ".join(v.unexpected))
    row["details"] = " | ".join(lines)
    store.upsert(PreAlert(ref=ref), Status.MAPPING_PASS if ok else Status.MAPPING_FAIL, f"{case.id}: {row['details']}")
    return row


def _validate_uat(cfg: Config, ui: UatPages, store: Store, case: Case, ref: str | None,
                  wait_seconds: float | None, row: dict) -> dict:
    """Real Nexus: newest pre-alert whose subject carries '| <case> |', then every parent's linked documents."""
    evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id
    if cfg.settings["validation"].get("evidence", True):
        row["evidence"] = str(evidence)
    v = cfg.settings["validation"]
    key = ref or case.id
    sent_at = store.last_sent_at(ref) if ref else None
    elapsed = (datetime.now() - sent_at).total_seconds() if sent_at else None
    sleep_s, wait = plan_wait(elapsed, v["initial_wait_seconds"], v["max_wait_seconds"], wait_seconds)
    _buffer(sleep_s, case.id)
    started = datetime.now()
    cell, info = ui.wait_for_case(f"{case.id} |", wait, v["poll_seconds"])
    if cell is None:
        if row["evidence"]:
            ui.screenshot(evidence / "not_received.png")
        store.upsert(PreAlert(ref=key), Status.NOT_RECEIVED, f"{case.id}: not in Nexus after {int(wait)}s")
        row.update(nexus_status="NOT_RECEIVED", verdict="FAIL", details=f"no pre-alert for {case.id} after {int(wait)}s")
        return row
    since_send = int((datetime.now() - sent_at).total_seconds()) if sent_at else int((datetime.now() - started).total_seconds())
    row.update(ipa=info["ipa"], appeared_after_s=since_send, nexus_status="CREATED_IN_NEXUS")
    store.upsert(PreAlert(ref=key), Status.CREATED_IN_NEXUS, f"{case.id}: {info['ipa']} seen {row['appeared_after_s']}s after sending")
    if row["evidence"]:
        ui.screenshot(evidence / "list.png")
    ui.open_viewer(cell)
    parents = ui.read_parents(evidence if row["evidence"] else None)
    actual = []
    for p in parents:
        for group, section in (("linked", p["kind"]), ("unmatched", "Unmatched"), ("unclassified", "Unclassified")):
            for g in p[group]:
                actual.append({"section": section, "name": g["label"], "type": g["label"]})
    expected = parse_expected(case.expected_mapping, case.docs, cfg)
    if not expected:
        row.update(verdict="ERROR", details="could not read an expected mapping from the test case")
        return row
    alternates = {k: [x.upper() for x in vals] for k, vals in (cfg.settings["validation"].get("type_alternates") or {}).items()}
    v = compare(expected, actual, cfg.settings["validation"]["type_aliases"], accept={"MANIFEST": {"Manifest"}}, alternates=alternates)
    ok = v.passed(cfg.settings["validation"].get("fail_on_unexpected", False))
    row["verdict"] = "PASS" if ok else "FAIL"
    seen = "; ".join(f"{p['parent']}: " + (", ".join(f"{g['label']}x{max(g['pages'],1)}" for g in p["linked"]) or "-") for p in parents)
    lines = [f"{r.doc_type}: {r.status} ({r.detail})" for r in v.results]
    if v.unexpected:
        lines.append("unexpected: " + "; ".join(v.unexpected))
    row["details"] = " | ".join(lines + [f"{info['ipa']} seen -> {seen}"])
    store.upsert(PreAlert(ref=key), Status.MAPPING_PASS if ok else Status.MAPPING_FAIL, f"{case.id}: {row['details']}")
    return row


def run_validate(cfg: Config, cases: list[Case], headless: bool = True, ref: str | None = None,
                 wait_seconds: float | None = None) -> list[dict]:
    store = Store(cfg.state_dir / "agent.db")
    rows: list[dict] = []
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            pages = UatPages(sess.page, cfg) if "uat" in cfg.selectors else NexusPages(sess.page, cfg)
            for case in cases:
                try:
                    rows.append(validate_case(cfg, pages, store, case, ref, wait_seconds))
                except SessionExpired:
                    raise
                except Exception as exc:                       # keep going with the other cases
                    log.exception("validation of %s failed", case.id)
                    pages.screenshot(cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case.id / "error.png")
                    rows.append({"case_id": case.id, "ref": ref or "", "ipa": "", "nexus_status": "ERROR", "verdict": "ERROR",
                                 "appeared_after_s": "", "details": f"{type(exc).__name__}: {exc}"[:300], "evidence": ""})
    except SessionExpired as exc:
        rows.append({"case_id": "-", "ref": "", "ipa": "", "nexus_status": "SESSION_EXPIRED", "verdict": "ERROR",
                     "appeared_after_s": "", "details": str(exc), "evidence": ""})
    return rows


def write_report(cfg: Config, rows: list[dict]) -> Path:
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"validate_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fields = ["case_id", "ref", "ipa", "nexus_status", "verdict", "appeared_after_s", "details", "evidence"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path
