"""Test-suite driven runs: reads test cases from the Excel suite, files downloaded samples per case,
stages them into the knowledge base, sends them and writes a per-case report."""
from __future__ import annotations

import csv
import glob
import logging
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config
from .local_sender import LocalSender

log = logging.getLogger(__name__)


@dataclass
class Case:
    id: str
    scenario: str
    mode: str                    # consolidated | individual
    docs: str
    sample_ref: str | None       # FJ number of the Quadance sample
    expected_mapping: str
    xml_rule: str
    expected_result: str
    nexus_job: str


def _clean(v) -> str:
    return re.sub(r"[ \t]+", " ", str(v)).strip() if v is not None else ""


def parse_rows(rows: list[list], ts: dict) -> list[Case]:
    """rows = sheet rows incl. the header row. Only in-scope rows are returned."""
    cols = ts["columns"]
    header = next((i for i, r in enumerate(rows) if _clean(r[0] if r else "") == cols["case_id"]), None)
    if header is None:
        raise ValueError(f"header row with '{cols['case_id']}' not found in the test-case tab")
    idx = {name: [_clean(h) for h in rows[header]].index(col) for name, col in cols.items()
           if col in [_clean(h) for h in rows[header]]}
    get = lambda r, k: _clean(r[idx[k]]) if k in idx and idx[k] < len(r) else ""
    cases = []
    for r in rows[header + 1:]:
        cid = get(r, "case_id")
        if not re.match(ts["id_pattern"], cid):
            continue
        scenario, docs = get(r, "scenario"), get(r, "docs")
        sl = scenario.lower()
        if not any(s.lower() in sl for s in ts["scenarios"]):
            continue
        if any(x.lower() in docs.lower() for x in ts.get("exclude_doc_contains", [])):
            continue
        m = re.search(ts["sample_ref_pattern"], get(r, "quadance_job"), re.IGNORECASE)
        cases.append(Case(cid, scenario, "consolidated" if "consolidated" in sl else "individual", docs,
                          m.group(1).upper() if m else None, get(r, "expected_mapping").replace("\n", " "),
                          get(r, "xml_rule"), get(r, "expected_result"), get(r, "nexus_job")))
    return cases


def read_cases(cfg: Config) -> list[Case]:
    import openpyxl
    ts = cfg.settings["testsuite"]
    files = sorted(glob.glob(str(cfg.path(ts["workbook"]))))
    files = [f for f in files if not Path(f).name.startswith("~$")]
    if not files:
        raise FileNotFoundError(f"no Excel file matches {ts['workbook']}")
    wb = openpyxl.load_workbook(files[-1], data_only=True, read_only=True)
    tab = next((w for w in wb.worksheets if w.title.lower().startswith(ts["sheet_tab"].lower())), None)
    if tab is None:
        raise ValueError(f"tab starting with '{ts['sheet_tab']}' not found in {Path(files[-1]).name}")
    return parse_rows([list(r) for r in tab.iter_rows(values_only=True)], ts)


# --- sample library ------------------------------------------------------------
def samples_root(cfg: Config) -> Path:
    return cfg.path(cfg.settings["testsuite"]["samples_dir"])


def sample_files(cfg: Config, case: Case) -> list[Path]:
    d = samples_root(cfg) / case.id
    return sorted(f for f in d.iterdir() if f.is_file()) if d.is_dir() else []


def ingest(cfg: Config, cases: list[Case]) -> tuple[dict[str, list[str]], list[str]]:
    """Files each download in samples/_inbox/ under the case(s) it belongs to, matched by test-case id or by
    FJ number in the file name. Returns ({case id: [file names]}, [unmatched file names])."""
    inbox = samples_root(cfg) / "_inbox"
    filed: dict[str, list[str]] = {}
    unmatched: list[str] = []
    for f in sorted(x for x in inbox.iterdir() if x.is_file()) if inbox.is_dir() else []:
        name = f.name.upper()
        hits = [c for c in cases if c.id in name] or [c for c in cases if c.sample_ref and c.sample_ref in name]
        if not hits:
            unmatched.append(f.name)
            continue
        for c in hits:
            dest = samples_root(cfg) / c.id
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest / f.name)
            filed.setdefault(c.id, []).append(f.name)
        f.unlink()
    return filed, unmatched


def individual_ref(cfg: Config, case: Case, files: list[Path]) -> str:
    """Reference for an individual set: the HAWB read from its PDFs, else the sample FJ, else the case id."""
    from .pdf_split import detect_parts, find_hawbs, page_texts
    kw = cfg.settings["pdf_split"]["keywords"]
    for f in files:
        if f.suffix.lower() == ".pdf":
            try:
                texts = page_texts(f.read_bytes())
                hawbs = find_hawbs(texts, detect_parts(texts, kw), cfg)
            except Exception:
                continue
            if hawbs:
                return hawbs[0]
    return case.sample_ref or case.id


# --- staging + run ---------------------------------------------------------------
def stage(cfg: Config, sender: LocalSender, case: Case) -> tuple[list[Path], str]:
    """Copies the case's samples into knowledge_base/. Returns (staged paths, problem or '')."""
    files = sample_files(cfg, case)
    if not files:
        return [], f"SAMPLE_MISSING: put the document(s) in samples/{case.id}/ or samples/_inbox/"
    if case.mode == "consolidated":
        if len(files) != 1:
            return [], f"NOT_STAGED: consolidated case needs exactly 1 file, found {len(files)}"
        targets = [sender._dir("consolidated_dir") / files[0].name]
    else:
        ref = individual_ref(cfg, case, files)
        targets = [sender._dir("individual_dir") / ref / f.name for f in files]
    clash = [t for t in targets if t.exists()]
    if clash:
        return [], f"NOT_STAGED: {clash[0].relative_to(sender.root)} already exists in the knowledge base"
    for src, dst in zip(files, targets):
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return targets, ""


def run_suite(cfg: Config, sender: LocalSender, cases: list[Case], dry_run: bool = False,
              force: bool = False, resend: bool = False, interval_seconds: float = 0,
              sleep=time.sleep, after_case=None) -> list[dict]:
    """Stages, screens and sends each case; returns one report row per email (or per problem)."""
    ts = cfg.settings["testsuite"]
    report: list[dict] = []
    sent_before = False                      # has a previous case in this run actually sent emails?
    for case in cases:
        if sent_before and interval_seconds and sample_files(cfg, case) and not dry_run:
            log.info("waiting %ds before case %s", interval_seconds, case.id)
            sleep(interval_seconds)
        base = {"case_id": case.id, "scenario": case.scenario, "mode": case.mode, "sample_ref": case.sample_ref or "",
                "nexus_job": case.nexus_job, "expected_mapping": case.expected_mapping,
                "expected_result": case.expected_result, "subject": "", "sent_at": "", "screening": "",
                "warnings": "", "actual_nexus_result": ""}
        staged, problem = stage(cfg, sender, case)
        if problem:
            status, _, msg = problem.partition(": ")
            report.append({**base, "status": status, "warnings": msg})
            continue
        if ts.get("subject_includes_case_id", True):
            sender.case_for_path.update({p: case.id for p in staged})
        before = len(sender.results)
        try:
            sender.send_all(dry_run=dry_run, force=force, only=set(staged), resend=resend)
        finally:
            handled = {r["path"] for r in sender.results[before:]}
            for p in staged:                      # remove staged copies that were not sent (the sample stays in samples/)
                if p.exists():
                    p.unlink()
                    try:
                        p.parent.rmdir() if p.parent.parent == sender._dir("individual_dir") else None
                    except OSError:
                        pass
        sent_before = sent_before or any(r["status"] == "SENT" for r in sender.results[before:])
        for r in sender.results[before:]:
            report.append({**base, "status": r["status"], "subject": r["subject"], "sent_at": r["sent_at"],
                           "screening": r["screening"], "warnings": r["warnings"]})
        for p in staged:
            if p not in handled:
                report.append({**base, "status": "ALREADY_SENT", "warnings": f"{p.name}: use --resend to send again"})
        if after_case:                       # e.g. validate the pre-alert in the Nexus UI right after this case was sent
            after_case(case, [r for r in report if r["case_id"] == case.id])
    return report


def write_report(cfg: Config, rows: list[dict]) -> Path:
    out = cfg.runs_dir / "_reports"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"suite_{datetime.now():%Y%m%d_%H%M%S}.csv"
    fields = ["case_id", "scenario", "mode", "sample_ref", "status", "subject", "sent_at", "screening", "warnings",
              "expected_mapping", "expected_result", "nexus_job", "actual_nexus_result"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path
