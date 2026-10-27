"""OCR for scanned pages (no text layer). Used only when CHECKING documents against Nexus, never when sending.
Engine: RapidOCR (onnxruntime, CPU, pip only). The page is turned to the right orientation, the text is rebuilt line by line,
and the result is cached on disk (state/ocr_cache), so a page is read once. OCR can misread characters, so callers treat what
it finds as REVIEW material, never as a hard FAIL."""
from __future__ import annotations

import hashlib
import json
import logging
import statistics
from pathlib import Path

log = logging.getLogger(__name__)
CACHE = Path(__file__).resolve().parent.parent / "state" / "ocr_cache"
_engine = None


def available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        import pypdfium2  # noqa: F401
        return True
    except Exception:
        return False


def _ocr(image):
    global _engine
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    _engine = _engine or RapidOCR()
    res, _ = _engine(np.array(image))
    out = []
    for box, text, conf in (res or []):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append({"text": text, "conf": float(conf), "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys)})
    return out


def _score(boxes: list[dict]) -> float:
    return sum(b["conf"] * len([c for c in b["text"] if c.isalnum()]) for b in boxes)


def _tall_ratio(boxes: list[dict]) -> float:
    tall = [b for b in boxes if (b["y1"] - b["y0"]) > 1.5 * (b["x1"] - b["x0"]) and len(b["text"]) > 2]
    return len(tall) / max(1, len(boxes))


def _lines(boxes: list[dict]) -> str:
    """Boxes -> text, one line per row of the page (boxes whose vertical centres are close), left to right."""
    if not boxes:
        return ""
    h = statistics.median(b["y1"] - b["y0"] for b in boxes) or 10
    rows: list[list[dict]] = []
    for b in sorted(boxes, key=lambda b: (b["y0"] + b["y1"]) / 2):
        c = (b["y0"] + b["y1"]) / 2
        if rows and abs(c - statistics.mean((x["y0"] + x["y1"]) / 2 for x in rows[-1])) < 0.6 * h:
            rows[-1].append(b)
        else:
            rows.append([b])
    return "\n".join(" ".join(x["text"] for x in sorted(r, key=lambda b: b["x0"])) for r in rows)


def ocr_page(pdf_bytes: bytes, index: int) -> dict:
    """{'text', 'rotation', 'lines'} of one page. Cached by (file hash, page)."""
    key = hashlib.sha1(pdf_bytes).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{key}_{index}.json"
    if f.exists():
        return json.loads(f.read_text())
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_bytes)
    img = pdf[index].render(scale=2.5).to_pil().convert("RGB")
    best_rot, best = 0, _ocr(img)
    if _tall_ratio(best) > 0.4 or (best and statistics.mean(b["conf"] for b in best) < 0.8):      # sideways or upside-down scan
        for rot in (90, 270, 180):
            cand = _ocr(img.rotate(rot, expand=True))
            if _score(cand) > _score(best):
                best_rot, best = rot, cand
    out = {"text": _lines(best), "rotation": best_rot, "lines": len(best)}
    f.write_text(json.dumps(out))
    log.info("OCR page %s: %d lines, rotated %d", index + 1, len(best), best_rot)
    return out


def page_text(pdf_bytes: bytes, index: int) -> str:
    try:
        return ocr_page(pdf_bytes, index)["text"] if available() else ""
    except Exception as exc:
        log.warning("OCR failed on page %d: %s", index + 1, exc)
        return ""
