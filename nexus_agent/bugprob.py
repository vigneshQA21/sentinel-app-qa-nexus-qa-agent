"""How likely is a finding to be a real bug? Learned from what happened to earlier findings, never hard-coded.

History = every decided finding: logged to the bug sheet (real unless the sheet says 'Not an issue' / 'Issue Not reproduced') or marked
'not a bug' by the user. Undecided (PENDING) findings are ignored. P = (real + 1) / (decided + 2) over the most specific group that has enough
decisions: (nature, document, field) -> (nature, document) -> (nature, field) -> nature -> everything. It only orders the review list and is
never a verdict; nothing goes to the bug sheet without the user's yes."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)
NOT_REAL_SHEET = ("not an issue", "issue not reproduced")
MIN = {"field": 3, "document": 3, "label": 4, "nature": 3}


def _label(field: str) -> str:
    return field.split("·")[-1].strip() if "·" in field else field.strip()


def cache_file(cfg) -> Path:
    return cfg.state_dir / "bug_patterns.json"


def history_from_store(store, sheet_status: dict[int, str] | None = None) -> list[list]:
    """[[document, label, nature, real], ...] from the local decisions (+ the sheet's statuses for the logged ones)."""
    out = []
    for status in ("LOGGED", "NOT_A_BUG"):
        for rec in store.bugs_by_status(status):
            try:
                d = json.loads(rec["data"])
            except Exception:
                continue
            real = False
            if status == "LOGGED":
                m = re.search(r"!A(\d+):", rec["note"] or "")
                s = (sheet_status or {}).get(int(m.group(1)), "") if m else ""
                real = s.strip().lower() not in NOT_REAL_SHEET
            out.append([d.get("document", ""), _label(d.get("field", "")), "mismatch" if (d.get("shown") or "").strip() else "missing", real])
    return out


def refresh(cfg, store, sheets=None) -> dict:
    """Rebuilds the cache from the bug sheet's statuses and the local decisions (needs the Google login)."""
    from . import bugs as B
    sheets = sheets or B.sheets_service(cfg)
    bs = cfg.settings["bugsheet"]
    hdr = B.sheet_state(cfg)["header"]
    rows = sheets.spreadsheets().values().get(spreadsheetId=bs["spreadsheet_id"], range="'" + (B.sheet_state(cfg).get("tab_name") or bs.get("tab_name") or "UAT Functionality Bugs") + "'!A1:Z3000").execute().get("values", [])
    st_i = hdr.index("Status")
    status = {int(r[0]): (r[st_i] if st_i < len(r) else "") for r in rows[1:] if r and r[0].strip().isdigit()}
    rec = history_from_store(store, status)
    data = {"built": datetime.now().isoformat(timespec="seconds"), "records": rec,
            "sheet_rows": len(status), "sheet_status": {}}
    for s in status.values():
        data["sheet_status"][s or "(blank)"] = data["sheet_status"].get(s or "(blank)", 0) + 1
    cache_file(cfg).write_text(json.dumps(data), encoding="utf-8")
    return data


class Patterns:
    def __init__(self, records: list[list]):
        self.rec = records

    @classmethod
    def load(cls, cfg, store) -> "Patterns":
        f = cache_file(cfg)
        if f.exists():
            try:
                return cls(json.loads(f.read_text(encoding="utf-8"))["records"])
            except Exception:
                log.warning("bug pattern cache unreadable, using the local decisions only")
        return cls(history_from_store(store))

    def _group(self, pred) -> tuple[int, int]:
        g = [r for r in self.rec if pred(r)]
        return sum(1 for r in g if r[3]), len(g)

    def estimate(self, document: str, field: str, nat: str) -> tuple[float, str]:
        """(probability the finding is a real bug, the basis in words)."""
        label, word = _label(field), ("MISSING" if nat == "missing" else "MISMATCH")
        tiers = [(MIN["field"], lambda r: r[2] == nat and r[0] == document and r[1] == label, f"{document} · {label} {word}"),
                 (MIN["document"], lambda r: r[2] == nat and r[0] == document, f"{document} {word}"),
                 (MIN["label"], lambda r: r[2] == nat and r[1] == label, f"{label} {word}"),
                 (MIN["nature"], lambda r: r[2] == nat, f"all {word}"),
                 (1, lambda r: True, "all findings")]
        for need, pred, name in tiers:
            real, n = self._group(pred)
            if n >= need:
                return (real + 1) / (n + 2), f"real {real} of {n} earlier {name} findings"
        return 0.5, "no history yet"
