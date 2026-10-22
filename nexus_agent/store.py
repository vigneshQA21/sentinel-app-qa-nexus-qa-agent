"""SQLite status store: lets a rerun resume and guarantees a shipment is never pushed twice."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import PreAlert, Status, RESUMABLE

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipments (
    ref TEXT PRIMARY KEY,
    gmail_id TEXT,
    subject TEXT,
    attachment_count INTEGER,
    status TEXT,
    detail TEXT,
    pushed_at TEXT,
    snapshot_path TEXT,
    evidence_dir TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS sent_docs (
    ref TEXT,
    filename TEXT,
    gmail_id TEXT,
    sent_at TEXT,
    PRIMARY KEY (ref, filename)
);
CREATE TABLE IF NOT EXISTS forwarded (
    gmail_id TEXT PRIMARY KEY,
    ref TEXT,
    forwarded_at TEXT
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- Gmail dedupe ---------------------------------------------------
    def was_forwarded(self, gmail_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM forwarded WHERE gmail_id=?", (gmail_id,)).fetchone() is not None

    def was_doc_sent(self, ref: str, filename: str) -> bool:
        return self.db.execute("SELECT 1 FROM sent_docs WHERE ref=? AND filename=?",
                               (ref, filename)).fetchone() is not None

    def mark_doc_sent(self, pa: PreAlert, filename: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO sent_docs VALUES (?,?,?,?)",
                        (pa.ref, filename, pa.gmail_id, _now()))
        self.upsert(pa, Status.FORWARDED, f"sent {filename}")

    def ref_for_case(self, case_id: str) -> str | None:
        """Reference (HAWB / FJ) of the latest email sent for a test case, read from the stored subject."""
        row = self.db.execute("SELECT ref FROM shipments WHERE subject LIKE ? ORDER BY updated_at DESC LIMIT 1",
                              (f"%{case_id} |%",)).fetchone()
        return row["ref"] if row else None

    def last_sent_at(self, ref: str) -> datetime | None:
        """When the latest email for this reference was sent."""
        row = self.db.execute("SELECT MAX(sent_at) AS t FROM sent_docs WHERE ref=?", (ref,)).fetchone()
        return datetime.fromisoformat(row["t"]) if row and row["t"] else None

    def mark_forwarded(self, pa: PreAlert) -> None:
        self.db.execute("INSERT OR IGNORE INTO forwarded VALUES (?,?,?)", (pa.gmail_id, pa.ref, _now()))
        self.upsert(pa, Status.FORWARDED, "forwarded to Nexus")

    # --- shipments --------------------------------------------------------
    def upsert(self, pa: PreAlert, status: Status, detail: str = "") -> None:
        self.db.execute(
            """INSERT INTO shipments(ref, gmail_id, subject, attachment_count, status, detail, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(ref) DO UPDATE SET
                 gmail_id=COALESCE(excluded.gmail_id, gmail_id),
                 subject=COALESCE(NULLIF(excluded.subject,''), subject),
                 attachment_count=COALESCE(excluded.attachment_count, attachment_count),
                 status=excluded.status, detail=excluded.detail, updated_at=excluded.updated_at""",
            (pa.ref, pa.gmail_id, pa.subject, pa.attachment_count, status.value, detail, _now()))
        self.db.commit()

    def set(self, ref: str, **cols) -> None:
        cols["updated_at"] = _now()
        sets = ", ".join(f"{k}=?" for k in cols)
        self.db.execute(f"UPDATE shipments SET {sets} WHERE ref=?", (*cols.values(), ref))
        self.db.commit()

    def get(self, ref: str) -> dict | None:
        row = self.db.execute("SELECT * FROM shipments WHERE ref=?", (ref,)).fetchone()
        return dict(row) if row else None

    def resumable(self) -> list[PreAlert]:
        marks = ",".join("?" for _ in RESUMABLE)
        rows = self.db.execute(f"SELECT * FROM shipments WHERE status IN ({marks})",
                               [s.value for s in RESUMABLE]).fetchall()
        return [PreAlert(ref=r["ref"], gmail_id=r["gmail_id"], subject=r["subject"] or "",
                         attachment_count=r["attachment_count"]) for r in rows]

    def load_snapshot(self, ref: str) -> dict | None:
        row = self.get(ref)
        if row and row.get("snapshot_path") and Path(row["snapshot_path"]).exists():
            return json.loads(Path(row["snapshot_path"]).read_text(encoding="utf-8"))
        return None
