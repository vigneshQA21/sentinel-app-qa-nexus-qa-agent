"""Orchestrator: runs each pre-alert through forward -> find -> classify -> shipper -> push -> XML check."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from .checks.classification import check_classification
from .checks.shipper import evaluate_shipper, load_corrections
from .config import Config
from .models import PreAlert, ShipmentResult, Status
from .nexus.pages import NexusPages
from .nexus.session import NexusSession, SessionExpired
from .report import write_report
from .store import Store
from .xml_reconcile import reconcile, is_clean

log = logging.getLogger("nexus_agent")


class Agent:
    def __init__(self, cfg: Config, dry_run: bool = False, headless: bool = True):
        self.cfg = cfg
        self.dry_run = dry_run
        self.headless = headless
        self.store = Store(cfg.state_dir / "agent.db")

    # ------------------------------------------------------------------
    def collect(self, refs: list[str] | None, use_gmail: bool) -> list[PreAlert]:
        items: dict[str, PreAlert] = {}
        for pa in self.store.resumable():              # retry earlier NOT_RECEIVED / APPROVAL_PENDING
            items[pa.ref] = pa
        if refs:
            for r in refs:
                items.setdefault(r, PreAlert(ref=r))
        if use_gmail:
            from .gmail_forwarder import GmailForwarder
            for pa in GmailForwarder(self.cfg, self.store).forward_new(self.dry_run):
                items[pa.ref] = pa
        return list(items.values())

    def run(self, refs: list[str] | None = None, use_gmail: bool = True) -> tuple[list[ShipmentResult], Path]:
        prealerts = self.collect(refs, use_gmail)
        log.info("Processing %d pre-alert(s)%s", len(prealerts), " [DRY RUN]" if self.dry_run else "")
        results: list[ShipmentResult] = []
        if prealerts:
            with NexusSession(self.cfg, headless=self.headless) as sess:
                pages = NexusPages(sess.page, self.cfg)
                for pa in prealerts:
                    try:
                        sess.ensure_logged_in()
                    except SessionExpired as exc:
                        log.error(str(exc))
                        results += [ShipmentResult(p.ref, Status.ERROR, [str(exc)])
                                    for p in prealerts[len(results):]]
                        break
                    results.append(self.process_with_retry(pa, pages))
        report_dir = write_report(results, self.cfg.runs_dir)
        log.info("Report: %s", report_dir / "summary.html")
        return results, report_dir

    # ------------------------------------------------------------------
    def process_with_retry(self, pa: PreAlert, pages: NexusPages) -> ShipmentResult:
        retries = int(self.cfg.settings["timing"].get("ui_retries", 2))
        evidence = self.cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / pa.ref
        evidence.mkdir(parents=True, exist_ok=True)
        last_exc, res = None, None
        for attempt in range(retries + 1):
            try:
                res = self.process(pa, pages, evidence)
                break
            except Exception as exc:  # UI error: screenshot + html, then retry
                last_exc = exc
                log.exception("%s attempt %d failed", pa.ref, attempt + 1)
                pages.screenshot(evidence / f"error_{attempt + 1}.png")
                pages.dump_html(evidence / f"error_{attempt + 1}.html")
                if self.store.get(pa.ref) and self.store.get(pa.ref).get("pushed_at"):
                    break  # never re-run a pushed shipment blindly; next run resumes at approval
        if res is None:
            pushed = (self.store.get(pa.ref) or {}).get("pushed_at")
            # A pushed shipment stays resumable so the next run checks approval + XML instead of pushing again.
            res = ShipmentResult(pa.ref, Status.APPROVAL_PENDING if pushed else Status.ERROR,
                                 [f"{type(last_exc).__name__}: {last_exc}"])
        res.evidence_dir = str(evidence)
        (evidence / "result.json").write_text(json.dumps(res.to_dict(), indent=2, default=str), encoding="utf-8")
        self.store.upsert(pa, res.status, " | ".join(res.messages)[:2000])
        self.store.set(pa.ref, evidence_dir=str(evidence))
        log.info("%s -> %s %s", pa.ref, res.status.value, "; ".join(res.messages))
        return res

    def process(self, pa: PreAlert, pages: NexusPages, evidence: Path) -> ShipmentResult:
        cfg, t = self.cfg, self.cfg.timing
        res = ShipmentResult(pa.ref, Status.ERROR)
        prior = self.store.get(pa.ref) or {}

        # 3. find the pre-alert in Nexus
        found = pages.wait_for_prealert(pa.ref, t("prealert_wait_seconds"), t("prealert_poll_seconds"))
        if not found:
            res.status = Status.NOT_RECEIVED
            res.messages.append(f"Not found in Nexus after {int(t('prealert_wait_seconds'))}s")
            return res
        pages.open_prealert(pa.ref)

        # Already pushed on an earlier run: resume at approval, never push twice.
        if prior.get("pushed_at"):
            snapshot = self.store.load_snapshot(pa.ref) or pages.read_shipper()
            res.messages.append(f"Resumed: pushed at {prior['pushed_at']}")
            return self._approve_and_reconcile(res, pages, snapshot, evidence)

        pages.screenshot(evidence / "01_opened.png")

        # 4. document classification
        docs = pages.read_documents()
        res.documents = docs
        ok, issues, counts = check_classification(docs, cfg.rules, pa.attachment_count)
        res.messages += issues
        if not ok:
            res.status = Status.CLASSIFICATION_FAIL
            pages.screenshot(evidence / "02_classification_fail.png")
            return res

        # 5. shipper data: validate, fix, edit
        current = pages.read_shipper()
        corrections = load_corrections(cfg.corrections_dir, pa.ref)
        target, edits, problems = evaluate_shipper(current, cfg.rules, corrections)
        res.edits = edits
        (evidence / "shipper_before.json").write_text(json.dumps(current, indent=2), encoding="utf-8")
        if problems:
            res.status = Status.NEEDS_REVIEW
            res.messages += problems
            pages.screenshot(evidence / "03_needs_review.png")
            return res
        if self.dry_run:
            res.status = Status.DRY_RUN_OK
            res.messages.append(f"{len(edits)} edit(s) would be saved; no push in dry run")
            return res
        if edits:
            after = pages.edit_shipper({e["field"]: e["new"] for e in edits})
            not_saved = [e["field"] for e in edits if after.get(e["field"]) != e["new"]]
            if not_saved:
                res.status = Status.EDIT_FAIL
                res.messages.append("Edit not saved for: " + ", ".join(not_saved))
                pages.screenshot(evidence / "04_edit_fail.png")
                return res
            res.messages.append(f"{len(edits)} shipper edit(s) saved")

        # 6. snapshot, then push
        snapshot = pages.read_shipper()
        snap_path = evidence / "snapshot_before_push.json"
        snap_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        self.store.upsert(pa, Status.APPROVAL_PENDING, "pushing")
        self.store.set(pa.ref, snapshot_path=str(snap_path))
        pages.push_to_tms()
        self.store.set(pa.ref, pushed_at=datetime.now().isoformat(timespec="seconds"))
        pages.screenshot(evidence / "05_pushed.png")
        return self._approve_and_reconcile(res, pages, snapshot, evidence)

    def _approve_and_reconcile(self, res: ShipmentResult, pages: NexusPages,
                               snapshot: dict, evidence: Path) -> ShipmentResult:
        t = self.cfg.timing
        state = pages.wait_for_approval(t("approval_wait_seconds"), t("approval_poll_seconds"))
        if state == "pending":
            res.status = Status.APPROVAL_PENDING
            res.messages.append("TMS push not approved yet; will re-check next run")
            return res
        if state == "rejected":
            res.status = Status.REJECTED
            res.messages.append(f"TMS push rejected: {pages.tms_status()}")
            pages.screenshot(evidence / "06_rejected.png")
            return res

        # 7. capture XML and reconcile
        xml = pages.capture_xml(evidence)
        (evidence / "tms_push.xml").write_text(xml, encoding="utf-8")
        pages.screenshot(evidence / "06_xml.png")
        try:
            rows = reconcile(xml, snapshot, self.cfg.xml_mapping)
        except Exception as exc:
            res.status = Status.XML_MISMATCH
            res.messages.append(f"XML could not be parsed: {exc}")
            return res
        res.reconciliation = rows
        bad = [r for r in rows if r["result"] not in ("MATCH", "NOT_IN_NEXUS")]
        if bad:
            res.status = Status.XML_MISMATCH
            res.messages.append("XML mismatch: " + ", ".join(f"{r['field']} ({r['result']})" for r in bad))
        else:
            res.status = Status.PASS
            res.messages.append(f"All {len(rows)} mapped XML fields match")
        return res
