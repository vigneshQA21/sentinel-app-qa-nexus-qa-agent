"""Per-run report: CSV + HTML summary + JSON with full detail."""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime
from pathlib import Path

from .models import ShipmentResult

_COLOR = {"PASS": "#1a7f37", "DRY_RUN_OK": "#1a7f37", "APPROVAL_PENDING": "#9a6700",
          "NOT_RECEIVED": "#9a6700", "FORWARDED": "#9a6700"}


def write_report(results: list[ShipmentResult], runs_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = runs_dir / "_reports" / stamp
    out.mkdir(parents=True, exist_ok=True)

    (out / "results.json").write_text(json.dumps([r.to_dict() for r in results], indent=2, default=str),
                                      encoding="utf-8")

    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ref", "status", "edits", "xml_mismatches", "messages", "evidence_dir"])
        for r in results:
            bad = [x["field"] for x in r.reconciliation if x["result"] not in ("MATCH", "NOT_IN_NEXUS")]
            w.writerow([r.ref, r.status.value, len(r.edits), ";".join(bad), " | ".join(r.messages), r.evidence_dir])

    rows = []
    for r in results:
        color = _COLOR.get(r.status.value, "#cf222e")
        edits = "<br>".join(html.escape(f"{e['field']}: '{e['old']}' → '{e['new']}'") for e in r.edits) or "–"
        mism = "<br>".join(html.escape(f"{x['field']}: Nexus '{x['expected']}' / XML '{x['actual']}' ({x['result']})")
                           for x in r.reconciliation if x["result"] not in ("MATCH", "NOT_IN_NEXUS")) or "–"
        msgs = "<br>".join(html.escape(m) for m in r.messages) or "–"
        rows.append(f"<tr><td>{html.escape(r.ref)}</td><td style='color:{color};font-weight:600'>"
                    f"{r.status.value}</td><td>{edits}</td><td>{mism}</td><td>{msgs}</td></tr>")
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status.value] = counts.get(r.status.value, 0) + 1
    summary = " · ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    (out / "summary.html").write_text(f"""<!doctype html><meta charset="utf-8">
<title>Nexus agent run {stamp}</title>
<style>body{{font-family:system-ui,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #d0d7de;padding:6px 8px;vertical-align:top;font-size:13px;text-align:left}}
th{{background:#f6f8fa}}</style>
<h2>Nexus pre-alert run {stamp}</h2><p>{html.escape(summary)}</p>
<table><tr><th>Ref</th><th>Status</th><th>Shipper edits</th><th>XML mismatches</th><th>Notes</th></tr>
{''.join(rows)}</table>""", encoding="utf-8")
    return out
