"""Knowledge-base flow. Consolidated PDFs are screened and mailed unchanged (one email each);
files in individual/<REF>/ are mailed one email per file."""
from __future__ import annotations

import base64
import logging
import re
import shutil
from datetime import datetime
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path

from .config import Config
from .gmail_forwarder import GmailForwarder
from .models import PreAlert
from .pdf_split import detect_parts, find_hawbs, page_texts
from .store import Store

log = logging.getLogger(__name__)


@dataclass
class Screening:
    ref: str
    pages: int
    found: list[str]                       # e.g. ["MBL pages 1", "MANIFEST pages 2", "HBL pages 3"]
    types: set[str]
    ordered: list[str]                     # types in page order, no duplicates
    missing: list[str]
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not any(w.startswith("scanned") for w in self.warnings)


@dataclass
class Item:
    ref: str
    path: Path
    subject: str
    screening: Screening | None = None
    case: str | None = None


def build_message(path: Path, to_addr: str, subject: str, ref: str, priority: str = "") -> EmailMessage:
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["Subject"] = subject
    if priority.lower() == "high":
        msg["X-Priority"] = "1 (Highest)"
        msg["Importance"] = "High"
    msg.set_content(f"Pre-alert {ref}\n\nAttached document: {path.name}\n")
    pdf = path.suffix.lower() == ".pdf"
    msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf" if pdf else "octet-stream",
                       filename=path.name)
    return msg


class LocalSender:
    def __init__(self, cfg: Config, store: Store, forwarder: GmailForwarder | None = None):
        self.cfg = cfg
        self.ld = cfg.settings["local_docs"]
        self.store = store
        self.fwd = forwarder
        self.root = cfg.path(self.ld["root"])
        self.case_for_path: dict[Path, str] = {}     # staged file -> test case id (set by the test suite)
        self.results: list[dict] = []                # one entry per email handled by send_all

    def _subject(self, template: str, path: Path, **kw) -> tuple[str, str | None]:
        """Formats the subject; a test case id goes at the very start so testers can trace the email."""
        case = self.case_for_path.get(path)
        subject = template.format(tag=self.ld["subject_tag"], **kw)
        if case:
            subject = f"{case} | {subject}"
        return subject, case

    def _dir(self, key: str) -> Path:
        return self.root / self.ld[key]

    # --- screening (read only: the PDF is never modified or split) ------------
    def screen(self, pdf: Path) -> Screening:
        texts = page_texts(pdf.read_bytes())
        parts = detect_parts(texts, self.cfg.settings["pdf_split"]["keywords"])
        hawbs = find_hawbs(texts, parts, self.cfg)
        warnings = []
        if hawbs:
            ref = hawbs[0]
            if len(hawbs) > 1:
                warnings.append(f"{len(hawbs)} HAWBs found {hawbs}; subject uses the first")
        else:
            m = re.search(self.cfg.settings["references"]["job_pattern"], pdf.stem, re.IGNORECASE)
            ref = m.group(1).upper() if m else pdf.stem.upper()
            warnings.append(f"no HAWB found in the PDF text, using file name reference {ref}")
        if not sum(len(t) for t in texts):
            warnings.insert(0, "scanned PDF: no text layer, contents cannot be checked")
        types = {p.label for p in parts}
        required = self.cfg.settings.get("screening", {}).get("required_types", [])
        missing = [t for t in required if t not in types] if sum(len(t) for t in texts) else list(required)
        ordered = list(dict.fromkeys(p.label for p in parts if p.label != "OTHER"))
        return Screening(ref, len(texts), [f"{p.label} pages {p.page_range}" for p in parts], types,
                         ordered, missing, warnings)

    def label(self, doc_type: str) -> str:
        return self.ld["doc_labels"].get(doc_type, doc_type)

    def individual_type(self, path: Path, ref: str) -> str:
        """Type of an individual file: from its file name, else from the PDF text."""
        stem = path.stem.upper()
        if stem.startswith(ref.upper()):
            stem = stem[len(ref):]
        for tok in re.split(r"[^A-Z0-9]+", stem):
            if tok in self.ld["filename_types"]:
                return self.ld["filename_types"][tok]
        if path.suffix.lower() == ".pdf":
            try:
                for lb in detect_parts(page_texts(path.read_bytes()), self.cfg.settings["pdf_split"]["keywords"]):
                    if lb.label != "OTHER":
                        return lb.label
            except Exception as exc:
                log.warning("could not read %s: %s", path.name, exc)
        return "OTHER"

    # --- what is waiting to be sent ---------------------------------------------
    def pending(self, refs: list[str] | None = None, force: bool = False,
                only: set[Path] | None = None) -> list[Item]:
        wanted = {r.upper() for r in refs} if refs else None
        skip_off = force or not self.ld.get("skip_already_sent", False)     # True = do not check "already sent"
        items: list[Item] = []
        cons = self._dir("consolidated_dir")
        for pdf in sorted(cons.glob("*.pdf")) if cons.is_dir() else []:
            if only is not None and pdf not in only:
                continue
            sc = self.screen(pdf)
            if (wanted and sc.ref.upper() not in wanted) or (
                    not skip_off and self.store.was_doc_sent(sc.ref, pdf.name)):
                continue
            types = "+".join(self.label(t) for t in sc.ordered) or "UNCLASSIFIED"
            subject, case = self._subject(self.ld["consolidated_subject_template"], pdf, ref=sc.ref, types=types)
            items.append(Item(sc.ref, pdf, subject, sc, case))
        ind = self._dir("individual_dir")
        for folder in sorted(p for p in ind.iterdir() if p.is_dir()) if ind.is_dir() else []:
            if wanted and folder.name.upper() not in wanted:
                continue
            for f in sorted(x for x in folder.iterdir() if x.is_file()):
                if only is not None and f not in only:
                    continue
                if not skip_off and self.store.was_doc_sent(folder.name, f.name):
                    continue
                doc = self.label(self.individual_type(f, folder.name))
                subject, case = self._subject(self.ld["subject_template"], f, ref=folder.name, doc=doc)
                items.append(Item(folder.name, f, subject, None, case))
        return items

    def send_all(self, dry_run: bool = False, refs: list[str] | None = None,
                 force: bool = False, only: set[Path] | None = None, resend: bool = False) -> list[PreAlert]:
        sent: list[PreAlert] = []
        to = self.cfg.settings["gmail"]["forward_to"]
        for it in self.pending(refs, force or resend, only):
            sc = it.screening
            row = {"path": it.path, "ref": it.ref, "subject": it.subject, "case": it.case, "status": "",
                   "sent_at": "", "screening": "", "warnings": ""}
            self.results.append(row)
            if sc:
                row["screening"] = "; ".join(sc.found)
                row["warnings"] = "; ".join(sc.warnings + ([f"missing {', '.join(sc.missing)}"] if sc.missing else []))
                log.info("SCREENING %s: %d page(s): %s", it.path.name, sc.pages, "; ".join(sc.found) or "nothing detected")
                for w in sc.warnings:
                    log.info("    WARNING: %s", w)
                if sc.missing:
                    log.info("    MISSING required: %s", ", ".join(sc.missing))
                if not sc.ok and not force:
                    log.warning("    SCREENING FAILED: %s not sent (fix the file or use --force)", it.path.name)
                    row["status"] = "SCREENING_FAILED"
                    continue
            pa = PreAlert(ref=it.ref, subject=it.subject, attachment_count=1)
            row["status"] = "DRY_RUN" if dry_run else "SENT"
            if dry_run:
                log.info("[dry-run] would send '%s' (%s) to %s", it.subject, it.path.name, to)
            else:
                self.fwd = self.fwd or GmailForwarder(self.cfg, self.store)
                users = self.fwd.svc.users()
                msg = build_message(it.path, to, it.subject, it.ref, self.ld.get("priority", ""))
                resp = users.messages().send(
                    userId="me", body={"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}).execute()
                pa.gmail_id = resp["id"]
                try:
                    users.messages().modify(userId="me", id=resp["id"],
                                            body={"addLabelIds": [self.fwd._label_id()]}).execute()
                except Exception as exc:  # label is cosmetic; the mail is already sent
                    log.warning("could not label sent mail: %s", exc)
                row["sent_at"] = datetime.now().isoformat(timespec="seconds")
                self.store.mark_doc_sent(pa, it.path.name)
                if self.ld.get("archive_after_send", False):
                    self._archive(it)
                log.info("Sent '%s' to %s (message id %s)", it.subject, to, pa.gmail_id)
            sent.append(pa)
        return sent

    def _archive(self, it: Item) -> None:
        dest = self._dir("sent_dir") / it.ref
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / it.path.name
        if target.exists():
            target = dest / f"{it.path.stem}_{int(it.path.stat().st_mtime)}{it.path.suffix}"
        parent = it.path.parent
        shutil.move(str(it.path), str(target))
        if parent.parent == self._dir("individual_dir"):
            try:
                parent.rmdir()
            except OSError:
                pass
