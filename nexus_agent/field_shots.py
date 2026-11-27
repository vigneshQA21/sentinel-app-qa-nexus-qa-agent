"""Field-specific evidence captured in the run itself (standing order, 27 Nov 2026: "always capture in the run itself").

After the false-alarm guard, every row still FAIL / REVIEW gets its own screenshot while the viewer is open on that panel: the field is
scrolled into view and outlined in red, with the source document beside it. The path is stored in the row (`shot`) and becomes the bug
candidate's evidence, so a later visit to Nexus is not needed to show the failing field next to the bill's box.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)
MAX_SHOTS = 15                      # per panel: a page full of FAILs is a checker / layout problem, not 50 screenshots

_JS = """([label, section]) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(label);
  let stem = norm(section).split(' ')[0].replace(/s$/, '');
  if (stem.length < 4) stem = '';
  const leaves = [...document.querySelectorAll('legend, label, span, div, p, h3, h4')].filter(e => e.children.length === 0);
  const same = leaves.filter(e => norm(e.textContent) === want);
  if (!same.length) return null;
  // the section's own box first ('Consignee' -> heading 'Consignee Name And Address'), then the first field of that label after it
  const head = stem ? leaves.find(e => { const t = norm(e.textContent); return t.length < 45 && t !== want && t.replace(/'/g, '').startsWith(stem); }) : null;
  const el = (head && same.find(e => head.compareDocumentPosition(e) & Node.DOCUMENT_POSITION_FOLLOWING)) || same[0];
  let box = el, f = null;
  for (let k = 0; k < 6 && box && !f; k++) { box = box.parentElement; f = box && box.querySelector('select, input, textarea'); }
  const target = f || el;
  target.scrollIntoView({block: 'center'});
  document.querySelectorAll('[data-qa-shot]').forEach(x => { x.style.outline = ''; x.removeAttribute('data-qa-shot'); });
  target.setAttribute('data-qa-shot', '1'); target.style.outline = '3px solid #e11d48';
  return true;
}"""
_CLEAR = "() => document.querySelectorAll('[data-qa-shot]').forEach(x => { x.style.outline = ''; x.removeAttribute('data-qa-shot'); })"


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60]


def capture(ui, rows: list[dict], folder: Path, prefix: str) -> int:
    """Screenshots each FAIL / REVIEW row's field on the open panel. Returns how many were captured. Never raises."""
    n = 0
    for r in rows:
        if r.get("result") not in ("FAIL", "REVIEW") or n >= MAX_SHOTS:
            continue
        label = (r.get("label") or str(r.get("field", "")).split("·")[-1]).strip()
        if not label or label.startswith("("):
            continue
        try:
            if not ui.page.evaluate(_JS, [label, r.get("section", "")]):
                continue
            ui.page.wait_for_timeout(500)
            path = folder / f"{prefix}_field_{_safe(r.get('section', ''))}_{_safe(label)}.png"
            ui.screenshot(path)
            r["shot"] = str(path)
            n += 1
        except Exception as exc:                    # evidence must never break a check
            log.warning("field screenshot of %s failed: %s", label, str(exc).splitlines()[0][:120])
    try:
        ui.page.evaluate(_CLEAR)
    except Exception:
        pass
    return n
