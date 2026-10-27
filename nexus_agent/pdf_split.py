"""Splits one consolidated PDF into separate documents (MBL, HBL, invoice, ...) by page text,
and reads the shipment reference from the PDF text."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader, PdfWriter

from .config import Config


@dataclass
class Part:
    label: str          # MBL / HBL / INVOICE / PACKING / OTHER
    pages: list[int]    # 0-based page indexes

    @property
    def page_range(self) -> str:
        return f"{self.pages[0] + 1}-{self.pages[-1] + 1}" if len(self.pages) > 1 else str(self.pages[0] + 1)


def page_texts(pdf_bytes: bytes, ocr: bool = False) -> list[str]:
    """Text of every page. ocr=True reads pages that have no text layer (scans) with OCR (used when checking, not when sending)."""
    texts = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf_bytes)).pages]
    if ocr:
        from . import ocr as _ocr
        texts = [t if len(t.strip()) >= 25 else (_ocr.page_text(pdf_bytes, i) or t) for i, t in enumerate(texts)]
    return texts


def classify_page(text: str, keywords: dict[str, list[str]]) -> str | None:
    """First type (config order) whose phrase occurs on the page. A `_WEAK` / `__n` suffix only sets priority."""
    flat = " ".join(text.split())
    squashed = re.sub(r"\s+", "", text).upper()          # catches letter-spaced headings: C A R G O ...
    for label, phrases in keywords.items():
        for ph in phrases:
            if re.search(r"(?<![A-Z0-9])" + re.escape(ph) + r"(?![A-Z0-9])", flat, re.IGNORECASE):
                return re.sub(r"(_WEAK|__\d+)$", "", label)
            if len(ph) >= 8 and re.sub(r"\s+", "", ph).upper() in squashed:
                return re.sub(r"(_WEAK|__\d+)$", "", label)
    return None


def page_labels(texts: list[str], keywords: dict[str, list[str]]) -> list[str | None]:
    """Per-page type. An air waybill form that quotes a MAWB or HAWB is a house bill; otherwise the first
    such form is the master and later ones are houses."""
    labels = [classify_page(t, keywords) for t in texts]
    for i, lb in enumerate(labels):
        if lb == "AWBFORM":
            is_house = re.search(r"(?<![A-Z0-9])(?:MAWB|HAWB)", texts[i], re.IGNORECASE) is not None
            labels[i] = "HBL" if is_house or "MBL" in labels[:i] else "MBL"
    return labels


def detect_parts(texts: list[str], keywords: dict[str, list[str]]) -> list[Part]:
    """Consecutive pages of the same type form one document. Unmatched pages continue the previous document."""
    parts: list[Part] = []
    for i, label in enumerate(page_labels(texts, keywords)):
        label = label or (parts[-1].label if parts else "OTHER")
        if parts and parts[-1].label == label:
            parts[-1].pages.append(i)
        else:
            parts.append(Part(label, [i]))
    return parts


def find_hawbs(texts: list[str], parts: list[Part], cfg: Config) -> list[str]:
    """HAWB numbers read after 'HAWB No:' style labels (token must contain a digit); HBL pages first."""
    pat = re.compile(cfg.settings["pdf_split"]["hawb_label_pattern"], re.IGNORECASE)
    hbl = [i for p in parts if p.label == "HBL" for i in p.pages]
    order = hbl + [i for i in range(len(texts)) if i not in hbl]
    found: list[str] = []
    for i in order:
        for m in pat.finditer(" ".join(texts[i].split())):
            tok = re.sub(r"\s+", "", m.group(1)).upper().removesuffix("MAWB")
            if len(tok) >= 5 and any(c.isdigit() for c in tok) and tok not in found:
                found.append(tok)
    return found


def build_documents(pdf_bytes: bytes, parts: list[Part], ref: str) -> list[tuple[str, bytes]]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    used: dict[str, int] = {}
    docs = []
    for part in parts:
        w = PdfWriter()
        for i in part.pages:
            w.add_page(reader.pages[i])
        buf = io.BytesIO()
        w.write(buf)
        n = used[part.label] = used.get(part.label, 0) + 1
        suffix = "" if n == 1 else f"_{n}"
        docs.append((f"{ref}_{part.label}{suffix}.pdf", buf.getvalue()))
    return docs
