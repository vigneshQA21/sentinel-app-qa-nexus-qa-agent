"""Every Nexus UI action lives here. Selectors come from config/selectors.yaml."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout

from ..config import Config

log = logging.getLogger(__name__)


class NexusPages:
    def __init__(self, page: Page, cfg: Config):
        self.page = page
        self.cfg = cfg
        self.s = cfg.selectors

    # --- helpers ----------------------------------------------------------
    def _value(self, selector: str) -> str:
        loc = self.page.locator(selector).first
        tag = loc.evaluate("e => e.tagName").upper()
        if tag in ("INPUT", "TEXTAREA", "SELECT"):
            return loc.input_value()
        return loc.inner_text().strip()

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(path), full_page=True)
        except Exception as exc:  # never let evidence capture break the run
            log.warning("screenshot failed: %s", exc)

    def dump_html(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(self.page.content(), encoding="utf-8")
        except Exception as exc:
            log.warning("html dump failed: %s", exc)

    # --- pre-alert list -----------------------------------------------------
    def _row(self, ref: str):
        return self.page.locator(self.s["prealert_list"]["row"].format(ref=ref))

    def search_prealert(self, ref: str) -> bool:
        pl = self.s["prealert_list"]
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["home_path"])
        if pl.get("search_input"):
            self.page.fill(pl["search_input"], ref)
            if pl.get("search_button"):
                self.page.click(pl["search_button"])
            else:
                self.page.press(pl["search_input"], "Enter")
            self.page.wait_for_load_state()
        return self._row(ref).count() > 0

    def wait_for_prealert(self, ref: str, timeout_s: float, poll_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while True:
            if self.search_prealert(ref):
                return True
            if time.monotonic() >= deadline:
                return False
            log.info("%s not in Nexus yet, retrying in %ss", ref, poll_s)
            time.sleep(poll_s)

    def open_prealert(self, ref: str) -> None:
        row = self._row(ref).first
        link = row.locator(self.s["prealert_list"]["open_link"])
        (link.first if link.count() else row).click()
        self.page.wait_for_load_state()

    # --- documents ----------------------------------------------------------
    def read_documents(self) -> list[dict]:
        d = self.s["documents"]
        docs = []
        rows = self.page.locator(d["row"])
        for i in range(rows.count()):
            r = rows.nth(i)
            docs.append({"name": r.locator(d["name_cell"]).first.inner_text().strip(),
                         "type": r.locator(d["type_cell"]).first.inner_text().strip()})
        return docs

    # --- documents per section (Master / House) -------------------------------
    def read_mapping(self, evidence: Path | None = None) -> list[dict]:
        """Documents Nexus shows in each section of an opened pre-alert: [{section, name, type}]."""
        m = self.s["mapping"]
        out = []
        for sec in m["sections"]:
            if m.get("section_tab"):
                tab = self.page.locator(m["section_tab"].format(section=sec))
                if tab.count():
                    tab.first.click()
                    self.page.wait_for_load_state()
            box = self.page.locator(m["section"].format(section=sec))
            if evidence:
                self.screenshot(evidence / f"section_{sec}.png")
            if not box.count():
                continue
            rows = box.first.locator(m["doc_row"])
            for i in range(rows.count()):
                r = rows.nth(i)
                name = r.locator(m["doc_name"]).first.inner_text().strip() if m.get("doc_name") else r.inner_text().strip()
                typ = ""
                if m.get("doc_type") and r.locator(m["doc_type"]).count():
                    typ = r.locator(m["doc_type"]).first.inner_text().strip()
                out.append({"section": sec, "name": name, "type": typ})
        return out

    # --- shipper data -------------------------------------------------------
    def read_shipper(self) -> dict:
        return {f: self._value(sel) for f, sel in self.s["shipper"]["fields"].items()
                if self.page.locator(sel).count()}

    def edit_shipper(self, changes: dict) -> dict:
        """Types the changes into the edit form, saves, and returns the re-read values."""
        sh = self.s["shipper"]
        if sh.get("edit_button"):
            self.page.click(sh["edit_button"])
        for field, value in changes.items():
            sel = sh["fields"][field]
            loc = self.page.locator(sel).first
            if loc.evaluate("e => e.tagName").upper() == "SELECT":
                loc.select_option(label=value)
            else:
                loc.fill(value)
        self.page.click(sh["save_button"])
        if sh.get("saved_marker"):
            self.page.locator(sh["saved_marker"]).first.wait_for(state="visible")
        self.page.wait_for_load_state()
        return self.read_shipper()

    # --- TMS push -----------------------------------------------------------
    def tms_status(self) -> str:
        loc = self.page.locator(self.s["tms"]["status_label"])
        return loc.first.inner_text().strip() if loc.count() else ""

    def push_to_tms(self) -> None:
        t = self.s["tms"]
        self.page.click(t["push_button"])
        if t.get("confirm_button"):
            self.page.click(t["confirm_button"])
        self.page.wait_for_load_state()

    def wait_for_approval(self, timeout_s: float, poll_s: float) -> str:
        """Returns 'approved', 'rejected' or 'pending'."""
        t = self.s["tms"]
        deadline = time.monotonic() + timeout_s
        while True:
            status = self.tms_status()
            if t["approved_text"].lower() in status.lower():
                return "approved"
            if t.get("rejected_text") and t["rejected_text"].lower() in status.lower():
                return "rejected"
            if time.monotonic() >= deadline:
                return "pending"
            time.sleep(poll_s)
            self.page.reload()

    # --- XML capture --------------------------------------------------------
    def capture_xml(self, save_dir: Path) -> str:
        x = self.s["xml"]
        mode = self.cfg.settings.get("xml_capture", {}).get("mode", "text")
        if mode == "download":
            with self.page.expect_download() as dl:
                self.page.click(x["download_button"])
            target = save_dir / (dl.value.suggested_filename or "tms.xml")
            dl.value.save_as(str(target))
            return target.read_text(encoding="utf-8")
        if x.get("open_button") and self.page.locator(x["open_button"]).count():
            self.page.click(x["open_button"])
        if mode == "clipboard":
            self.page.click(x["copy_button"])
            return self.page.evaluate("navigator.clipboard.readText()")
        loc = self.page.locator(x["container"]).first
        try:
            loc.wait_for(state="visible", timeout=10000)
        except PWTimeout:
            loc.wait_for(state="attached")
        return loc.text_content() or ""
