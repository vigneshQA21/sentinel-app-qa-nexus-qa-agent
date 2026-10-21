"""Page actions for the real Nexus (UAT). Selectors come from config/selectors.uat.yaml.
Everything here is view-only: it never clicks Save, Verify, Approve, Push or Delete."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path

from playwright.sync_api import Page

from ..config import Config

log = logging.getLogger(__name__)


def parse_left_panel(text: str, headings: list[str]) -> dict:
    """Turns the viewer's left panel text into {linked: [{label, pages}], unmatched: [...], unclassified: [...]}.
    Under each heading the panel shows a group label (MAWB, INVOICE, ...) followed by one short code per page
    (AWB, INV, INV, ...). A code is recognised as 'a page of the previous group' when its letters appear, in order,
    inside the group label (AWB in MAWB, INV in INVOICE, PKG in PACKINGLIST, MAN in AIRMANIFEST)."""
    def is_page_code(code: str, group: str) -> bool:
        it = iter(group)
        return all(ch in it for ch in code)

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    sections: dict[str, list[str]] = {h: [] for h in headings}
    current = None
    for ln in lines:
        if ln.upper() in sections:
            current = ln.upper()
        elif current:
            sections[current].append(ln)

    def groups(items: list[str]) -> list[dict]:
        out: list[dict] = []
        for it in items:
            if out and is_page_code(it.upper(), out[-1]["label"]) and it.upper() != out[-1]["label"]:
                out[-1]["pages"] += 1
            else:
                out.append({"label": it.upper(), "pages": 0})
        return out

    return {"linked": groups(sections.get(headings[0], [])),
            "unmatched": groups(sections.get(headings[1], [])),
            "unclassified": groups(sections.get(headings[2], []))}


class UatPages:
    def __init__(self, page: Page, cfg: Config):
        self.page = page
        self.cfg = cfg
        self.u = cfg.selectors["uat"]

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(path))
        except Exception as exc:
            log.warning("screenshot failed: %s", exc)

    # --- list ---------------------------------------------------------------------------
    def open_list(self) -> None:
        self.page.goto(self.cfg.base_url + self.cfg.settings["nexus"]["home_path"])
        try:
            self.page.locator(self.u["row_marker"]).first.wait_for(state="visible", timeout=60000)   # rows are on the page
            self.page.locator(self.u["loading"]).first.wait_for(state="hidden", timeout=60000)
        except Exception:
            log.warning("the email list did not finish loading")
        self.page.wait_for_timeout(1000)

    def find_case_row(self, token: str):
        cells = self.page.locator(self.u["subject_cell"].format(token=token))
        return cells.first if cells.count() else None      # newest row first

    def row_info(self, cell) -> dict:
        """IPA id and job progress of the row that holds this subject cell."""
        node = cell
        for _ in range(int(self.u.get("row_ancestor_levels", 8))):
            node = node.locator("xpath=..")
            text = node.inner_text()
            m = re.search(r"IPA/\d+/\d{4}-\d{2}", text)
            if m:
                prog = re.findall(r"(\d+)%", text)
                return {"ipa": m.group(0), "progress": int(prog[0]) if prog else None}
        return {"ipa": "", "progress": None}

    def wait_for_case(self, token: str, timeout_s: float, poll_s: float, need_progress: bool = True):
        """Waits for the pre-alert row of a case to appear (and finish processing). Returns (cell, info) or (None, {})."""
        deadline = time.monotonic() + timeout_s
        while True:
            self.open_list()
            cell = self.find_case_row(token)
            if cell is not None:
                info = self.row_info(cell)
                if not need_progress or info["progress"] is None or info["progress"] >= 100 or time.monotonic() >= deadline:
                    return cell, info
            if time.monotonic() >= deadline:
                return None, {}
            log.info("%s not ready in Nexus yet, retrying in %ss", token, poll_s)
            time.sleep(poll_s)

    # --- viewer ---------------------------------------------------------------------------
    def open_viewer(self, cell) -> None:
        cell.click()
        self.page.wait_for_timeout(2500)
        self.page.get_by_label(self.u["view_documents"]).first.click()
        self.page.wait_for_url(f"**{self.u['viewer_url_part']}**", timeout=30000)
        self.page.wait_for_timeout(3000)

    def _parent_button(self):
        ignore = re.compile(self.u["header_buttons_ignore"])
        found = []
        for b in self.page.locator("button").all():
            box = b.bounding_box()
            txt = (b.inner_text() or "").strip()
            if box and box["y"] < 70 and txt and not ignore.search(txt):
                found.append((box["x"], b))
        found.sort(key=lambda t: t[0])
        return found[1][1] if len(found) > 1 else None      # [document type dropdown, parent dropdown]

    def _open_dropdown(self) -> None:
        """Opens the parent dropdown if it is not already open (Escape does not close it, a click toggles it)."""
        box = self.page.get_by_placeholder(self.u["parent_search"])
        if box.count():
            return
        btn = self._parent_button()
        if btn is None:
            raise RuntimeError("parent dropdown button not found in the viewer header")
        btn.click()
        box.first.wait_for(state="visible", timeout=10000)

    def parent_options(self) -> list[str]:
        self._open_dropdown()
        box = self.page.get_by_placeholder(self.u["parent_search"]).locator("xpath=ancestor::div[2]")
        return [ln.strip() for ln in box.inner_text().splitlines() if ln.strip()]

    def select_parent(self, name: str) -> None:
        self._open_dropdown()
        self.page.get_by_text(name, exact=True).last.click()        # the option (the header button shows the same text first)
        self.page.wait_for_timeout(2500)

    def read_left_panel(self) -> dict:
        heads = self.u["left_headings"]
        for h in heads[1:]:                                   # expand Unmatched / Unclassified
            try:
                self.page.get_by_text(h, exact=True).first.click()
                self.page.wait_for_timeout(500)
            except Exception:
                pass
        box = self.page.locator("div").filter(has_text=heads[0]).filter(has_text=heads[2]).last
        return parse_left_panel(box.inner_text(), heads)

    def read_parents(self, evidence: Path | None = None) -> list[dict]:
        """[{parent, kind, linked: [...], unmatched: [...], unclassified: [...]}] for every parent in the dropdown."""
        out = []
        for name in self.parent_options():
            self.select_parent(name)
            panel = self.read_left_panel()
            kind = "Master" if name.startswith("Master") else "House" if name.startswith("House") else \
                "Manifest" if "Manifest" in name else name
            out.append({"parent": name, "kind": kind, **panel})
            if evidence:
                self.screenshot(evidence / f"parent_{kind}.png")
        return out


CARGO_FIELDS = ["pieces", "pieces_unit", "gross_weight", "gross_unit", "chargeable_weight", "chargeable_unit",
                "nature", "volume", "volume_unit", "executed_on"]
CARGO_LABELS = ["Pieces", "Pieces Unit", "Gross Weight", "Gross Weight Unit", "Chargeable Weight",
                "Chargeable Weight Unit", "Nature And Quantity Of Goods", "Volume", "Volume Unit", "Executed On"]
PARTY_CARD = {"Shipper": "Shippers Name And Address", "Consignee": "Consignee Name And Address"}


def map_master_panel(items: list[dict], party_ids: dict | None = None) -> dict:
    """Turns the ordered inputs of the 'Shipment Data' panel (Master record) into named fields.
    items = [{tag, label, value, readonly}] in page order. The first unlabeled input is the AWB number; the unlabeled
    inputs after the 'Freight Payment' select are the cargo line. Returns the named values plus `fields`: EVERY field of
    the panel, in panel order, as {section, label, value, readonly} (nothing is dropped)."""
    out: dict = {"segments": [], "shipper": {}, "consignee": {}, "fields": []}
    party_ids = party_ids or {}
    seen: dict[str, int] = {}
    after_freight = 0

    def add(section, label, value, readonly=False):
        out["fields"].append({"section": section, "label": label, "value": value, "readonly": readonly})

    for it in items:
        label, value, ro = it["label"], it["value"], it["readonly"]
        if it["tag"] == "SELECT" and label == "Freight Payment":
            out["freight_payment"] = value
            add("Freight", "Freight Payment", value, ro)
            after_freight = 1
        elif after_freight and not label:
            idx = after_freight - 1
            if idx < len(CARGO_FIELDS):
                out[CARGO_FIELDS[idx]] = value
                add("Cargo", CARGO_LABELS[idx], value, ro)
            else:
                add("Cargo", f"(unlabelled field {idx + 1})", value, ro)
            after_freight += 1
        elif not label and "awb_number" not in out:
            out["awb_number"] = value
            add("Air Waybill", "Air Waybill Number", value, ro)
        elif label in ("Name", "Address", "Postal Code"):
            n = seen[label] = seen.get(label, 0) + 1
            who = "Shipper" if n == 1 else "Consignee"
            party = out[who.lower()]
            party[label.lower().replace(" ", "_")] = value
            party["readonly_" + label.lower().replace(" ", "_")] = ro
            add(who, label, value, ro)
            if label == "Postal Code":
                pid = party_ids.get(PARTY_CARD[who], "")
                party["party_id"] = pid
                add(who, "Party ID", pid, True)
        elif label == "Type":
            out["route_type"] = value
            add("Flight Route", "Type", value, ro)
        elif label == "From":
            out["segments"].append({"from": value})
            add(f"Segment {len(out['segments'])}", "From", value, ro)
        elif label in ("To", "Polname", "Polctry", "Podname", "Podctry", "Carrier Name", "Carrier Code",
                       "Flight Number", "Flight Date") and out["segments"]:
            out["segments"][-1][label.lower().replace(" ", "_")] = value
            add(f"Segment {len(out['segments'])}", label, value, ro)
        elif label == "Airport Of Departure":
            out["departure_airport"] = value
            add("Routing", label, value, ro)
        elif label == "Final Destination Airport":
            out["destination_airport"] = value
            add("Routing", label, value, ro)
        else:
            add("Other", label or "(unlabelled field)", value, ro)
    return out


def read_panel_inputs(page: Page) -> list[dict]:
    panel = page.get_by_text("Shipment Data", exact=True).first.locator("xpath=ancestor::div[2]")
    return panel.evaluate("""p => [...p.querySelectorAll('input,textarea,select')].map(e => ({
        tag: e.tagName,
        label: ([...e.parentElement.querySelectorAll('label,span')].map(x => x.innerText.trim()).filter(Boolean)[0] || '')
               || (e.tagName === 'SELECT' ? (e.getAttribute('aria-label') || '') : ''),
        value: e.tagName === 'SELECT' ? (e.selectedOptions[0] ? e.selectedOptions[0].text : e.value) : (e.value || ''),
        readonly: !!(e.readOnly || e.disabled)}))""")


def read_party_ids(page: Page) -> dict:
    """{'Shippers Name And Address': 'QUADIMNIC', ...} from the 'Party ID' buttons."""
    out = {}
    for b in page.locator("button[aria-label$='Party ID']").all():
        name = (b.get_attribute("aria-label") or "").replace(" — Party ID", "")
        out[name] = (b.inner_text() or "").replace("Party ID:", "").strip()
    return out
