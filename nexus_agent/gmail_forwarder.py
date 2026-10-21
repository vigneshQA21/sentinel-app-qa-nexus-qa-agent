"""Finds new pre-alert emails in Gmail and forwards them (with attachments) to the Nexus mailbox."""
from __future__ import annotations

import base64
import email
import logging
import re
from email.message import EmailMessage
from email.policy import default as default_policy

from .config import Config
from .models import PreAlert
from .store import Store

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]  # read, send, label


def extract_ref(text: str, cfg: Config) -> str | None:
    refs = cfg.settings["references"]
    order = ["hawb", "mawb"] if refs.get("match_by", "hawb") == "hawb" else ["mawb", "hawb"]
    for kind in order:
        m = re.search(refs[f"{kind}_pattern"], text or "", re.IGNORECASE)
        if m:
            val = m.group(1).upper()
            if kind == "mawb" and "-" not in val and len(val) == 11:
                val = f"{val[:3]}-{val[3:]}"
            return val
    return None


def _text_body(msg: email.message.EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        return part.get_content()
    except Exception:
        return (part.get_payload(decode=True) or b"").decode("utf-8", "replace")


def build_forward(orig: email.message.EmailMessage, to_addr: str, from_addr: str | None = None) -> EmailMessage:
    """Builds a forward that keeps every attachment byte-for-byte."""
    fwd = EmailMessage()
    fwd["To"] = to_addr
    if from_addr:
        fwd["From"] = from_addr
    subject = orig.get("Subject", "")
    fwd["Subject"] = subject if subject.lower().startswith("fwd:") else f"Fwd: {subject}"
    header = ("---------- Forwarded message ---------\n"
              f"From: {orig.get('From', '')}\nDate: {orig.get('Date', '')}\n"
              f"Subject: {subject}\nTo: {orig.get('To', '')}\n\n")
    fwd.set_content(header + _text_body(orig))
    for part in orig.iter_attachments():
        data = part.get_payload(decode=True) or b""
        maintype, _, subtype = part.get_content_type().partition("/")
        fwd.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=part.get_filename() or "attachment")
    return fwd


class GmailForwarder:
    def __init__(self, cfg: Config, store: Store):
        self.cfg = cfg
        self.g = cfg.settings["gmail"]
        self.store = store
        self._svc = None

    # --- auth -------------------------------------------------------------
    @property
    def svc(self):
        if self._svc is None:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build

            token = self.cfg.path(self.g["token_file"])
            creds = Credentials.from_authorized_user_file(str(token), SCOPES) if token.exists() else None
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.cfg.path(self.g["credentials_file"])), SCOPES)
                    creds = flow.run_local_server(port=0)
                token.parent.mkdir(parents=True, exist_ok=True)
                token.write_text(creds.to_json(), encoding="utf-8")
            self._svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._svc

    def _label_id(self) -> str:
        name = self.g["processed_label"]
        labels = self.svc.users().labels().list(userId="me").execute().get("labels", [])
        for lb in labels:
            if lb["name"] == name:
                return lb["id"]
        created = self.svc.users().labels().create(
            userId="me", body={"name": name, "labelListVisibility": "labelShow",
                               "messageListVisibility": "show"}).execute()
        return created["id"]

    # --- main -------------------------------------------------------------
    def forward_new(self, dry_run: bool = False) -> list[PreAlert]:
        users = self.svc.users()
        resp = users.messages().list(userId="me", q=self.g["query"],
                                     maxResults=self.g.get("max_messages_per_run", 50)).execute()
        msgs = resp.get("messages", [])
        log.info("Gmail: %d candidate pre-alert emails", len(msgs))
        label_id = None if dry_run else self._label_id()
        out: list[PreAlert] = []
        for m in msgs:
            if self.store.was_forwarded(m["id"]):
                continue
            raw = users.messages().get(userId="me", id=m["id"], format="raw").execute()["raw"]
            orig = email.message_from_bytes(base64.urlsafe_b64decode(raw), policy=default_policy)
            attachments = list(orig.iter_attachments())
            names = " ".join(a.get_filename() or "" for a in attachments)
            ref = extract_ref(f"{orig.get('Subject', '')}\n{_text_body(orig)}\n{names}", self.cfg)
            if not ref:
                log.warning("Gmail %s: no HAWB/MAWB found in '%s', skipped", m["id"], orig.get("Subject"))
                continue
            pa = PreAlert(ref=ref, gmail_id=m["id"], subject=orig.get("Subject", ""),
                          attachment_count=len(attachments))
            if dry_run:
                log.info("[dry-run] would forward %s (%s, %d attachments)", m["id"], ref, len(attachments))
            else:
                fwd = build_forward(orig, self.g["forward_to"])
                body = {"raw": base64.urlsafe_b64encode(fwd.as_bytes()).decode()}
                users.messages().send(userId="me", body=body).execute()
                users.messages().modify(userId="me", id=m["id"], body={"addLabelIds": [label_id]}).execute()
                self.store.mark_forwarded(pa)
                log.info("Forwarded %s (%s) to %s", m["id"], ref, self.g["forward_to"])
            out.append(pa)
        return out
