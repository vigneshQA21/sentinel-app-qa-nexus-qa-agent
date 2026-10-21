from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class Status(str, Enum):
    FORWARDED = "FORWARDED"
    CREATED_IN_NEXUS = "CREATED_IN_NEXUS"
    MAPPING_PASS = "MAPPING_PASS"
    MAPPING_FAIL = "MAPPING_FAIL"
    NOT_RECEIVED = "NOT_RECEIVED"
    CLASSIFICATION_FAIL = "CLASSIFICATION_FAIL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    EDIT_FAIL = "EDIT_FAIL"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    REJECTED = "REJECTED"
    XML_MISMATCH = "XML_MISMATCH"
    PASS = "PASS"
    DRY_RUN_OK = "DRY_RUN_OK"
    ERROR = "ERROR"


# Statuses that are retried automatically on the next run.
RESUMABLE = {Status.FORWARDED, Status.NOT_RECEIVED, Status.APPROVAL_PENDING}


@dataclass
class PreAlert:
    ref: str                              # HAWB or MAWB used to find it in Nexus
    gmail_id: str | None = None
    subject: str = ""
    attachment_count: int | None = None


@dataclass
class ShipmentResult:
    ref: str
    status: Status
    messages: list[str] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)
    edits: list[dict] = field(default_factory=list)
    reconciliation: list[dict] = field(default_factory=list)
    evidence_dir: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d
