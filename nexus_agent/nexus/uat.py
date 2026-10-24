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


def assign_columns(headers: list[tuple], leaves: list[tuple]) -> dict:
    """headers/leaves = [(text, x0, x1)]. Each text of a data row goes to the header whose centre is nearest to its own;
    texts in the same column are joined. A cell that only repeats its header text (an empty input's placeholder,
    e.g. 'Job Number') is returned as ''."""
    cols = [(h[0], (h[1] + h[2]) / 2) for h in headers]
    out: dict[str, list[str]] = {h[0]: [] for h in headers}
    for text, x0, x1 in leaves:
        centre = (x0 + x1) / 2
        name = min(cols, key=lambda c: abs(c[1] - centre))[0]
        out[name].append(text)
    return {k: ("" if " ".join(v) == k else " ".join(v)) for k, v in out.items()}


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
        url = self.cfg.base_url + self.cfg.settings["nexus"]["home_path"]
        for attempt in (1, 2):                                   # Nexus is sometimes slow: wait for the content, retry once
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                log.warning("Nexus was slow to load (%s), retrying", type(exc).__name__)
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
    def expand_row(self, cell) -> None:
        """Expands the pre-alert's row so its records and 'View documents' buttons show. A click toggles the row, and Nexus can bring a
        row back already expanded, so the result is checked and the click repeated once if the row ended up collapsed."""
        view = self.page.get_by_label(self.u["view_documents"])
        for _ in range(2):
            cell.click()
            self.page.wait_for_timeout(2500)
            if view.count():
                return

    def read_shipment_details(self) -> list[dict]:
        """The 'Shipment Details' table of the expanded row: one dict per record (Master / House), keyed by column."""
        raw = self.page.get_by_text("Record Type", exact=True).first.evaluate("""h => {
            let node = h.parentElement;
            for (let i = 0; i < 8; i++) {
              const sib = [...node.parentElement.children].filter(x => x !== node && /Master|House/.test(x.innerText));
              if (sib.length) break; node = node.parentElement; }
            const table = node.parentElement;
            const leaves = root => [...root.querySelectorAll('*')].filter(e => e.children.length === 0 && (e.innerText || '').trim())
                .map(e => { const r = e.getBoundingClientRect(); return [(e.innerText || '').replace(/\\s+/g, ' ').trim(), r.left, r.right]; });
            const rows = [...table.children].filter(x => x !== node && /Master|House/.test(x.innerText));
            return {headers: leaves(node), rows: rows.map(leaves)}; }""")
        return [assign_columns([tuple(x) for x in raw["headers"]], [tuple(x) for x in r]) for r in raw["rows"]]

    def open_viewer(self, cell, expanded: bool = False) -> None:
        if not expanded:
            self.expand_row(cell)
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


def map_house_panel(items: list[dict], party_ids: dict | None = None) -> dict:
    """The House record's 'Shipment Data' panel (a different layout from the Master's), every field in panel order.
    Order in Nexus: house number (Top Right / Bottom Right), master AWB reference, shipper, consignee, a free-text agent box,
    freight payment, airports, route + segments, cargo (pieces, weights, goods, volume), shipper's reference, dates, incoterm."""
    out: dict = {"segments": [], "shipper": {}, "consignee": {}, "fields": []}
    party_ids = party_ids or {}
    seen: dict[str, int] = {}
    stage = "head"
    unl = 0                       # unlabelled fields met in the current stage

    def add(section, label, value, readonly=False):
        out["fields"].append({"section": section, "label": label, "value": value, "readonly": readonly})

    for it in items:
        label, value, ro = it["label"], it["value"], it["readonly"]
        if label == "Top Right":
            out["house_top"] = value; add("House Air Waybill", "House Number (top right)", value, ro)
        elif label == "Bottom Right":
            out["house_bottom"] = value; add("House Air Waybill", "House Number (bottom right)", value, ro)
        elif not label and stage == "head" and "master_ref" not in out:
            out["master_ref"] = value; add("House Air Waybill", "Master AWB Reference", value, ro)
        elif label in ("Name", "Address", "Postal Code"):
            n = seen[label] = seen.get(label, 0) + 1
            who = "Shipper" if n == 1 else "Consignee"
            party = out[who.lower()]
            party[label.lower().replace(" ", "_")] = value
            add(who, label, value, ro)
            if label == "Postal Code":
                pid = party_ids.get(PARTY_CARD[who], "")
                party["party_id"] = pid
                add(who, "Party ID", pid, True)
        elif not label and it["tag"] == "TEXTAREA" and "agent_text" not in out and "freight_payment" not in out:
            out["agent_text"] = value; add("Agent", "Agent / Origin Party (free text)", value, ro)
        elif it["tag"] == "SELECT" and label == "Freight Payment":
            out["freight_payment"] = value; add("Freight", "Freight Payment", value, ro)
        elif label == "Airport Of Departure":
            out["departure_airport"] = value; add("Routing", label, value, ro)
        elif label == "Final Destination Airport":
            out["destination_airport"] = value; add("Routing", label, value, ro)
        elif label == "Type":
            out["route_type"] = value; add("Flight Route", "Type", value, ro)
        elif label == "From":
            out["segments"].append({"from": value}); add(f"Segment {len(out['segments'])}", "From", value, ro)
        elif label in ("To", "Polname", "Polctry", "Podname", "Podctry", "Carrier Name", "Carrier Code",
                       "Flight Number", "Flight Date") and out["segments"]:
            out["segments"][-1][label.lower().replace(" ", "_")] = value
            add(f"Segment {len(out['segments'])}", label, value, ro)
            if label == "Flight Date":
                stage = "cargo"; unl = 0
        elif stage == "cargo" and label == "Value" and "pieces" not in out:
            out["pieces"] = value; add("Cargo", "Pieces", value, ro)
        elif stage == "cargo" and label == "Unit" and "pieces_unit" not in out:
            out["pieces_unit"] = value; add("Cargo", "Pieces Unit", value, ro)
        elif stage == "cargo" and not label and "pieces_unit" in out and "volume" not in out:
            names = ["gross_weight", "gross_unit", "chargeable_weight", "chargeable_unit", "nature"]
            labels = ["Gross Weight", "Gross Weight Unit", "Chargeable Weight", "Chargeable Weight Unit", "Nature And Quantity Of Goods"]
            if unl < len(names):
                out[names[unl]] = value; add("Cargo", labels[unl], value, ro)
            else:
                add("Cargo", f"(unlabelled field {unl + 1})", value, ro)
            unl += 1
        elif stage == "cargo" and label == "Value" and "pieces" in out:
            out["volume"] = value; add("Cargo", "Volume", value, ro)
        elif stage == "cargo" and label == "Unit" and "volume" in out:
            out["volume_unit"] = value; add("Cargo", "Volume Unit", value, ro)
        elif label == "Shippers Reference":
            out["reference"] = value; add("Reference", "Shippers Reference", value, ro); stage = "tail"; unl = 0
        elif stage == "tail" and not label:
            tail = [("(unlabelled, empty)", None), ("Executed On", "executed_on"), ("(unlabelled, empty)", None), ("Incoterm", "incoterm")]
            lab, key = tail[unl] if unl < len(tail) else (f"(unlabelled field {unl + 1})", None)
            if key:
                out[key] = value
            add("Reference", lab, value, ro)
            unl += 1
        else:
            add("Other", label or "(unlabelled field)", value, ro)
    return out


def read_panel_fields(page: Page) -> list[dict]:
    """Like read_panel_inputs, but an input without its own label gets the nearest heading above it
    (Invoice Number, Grand Total ...). Used for Manifest / Invoice / Packing List panels."""
    panel = page.get_by_text("Shipment Data", exact=True).first.locator("xpath=ancestor::div[2]")
    return panel.evaluate("""p => [...p.querySelectorAll('input,textarea,select')].map(e => {
        let label = '';
        let n = e;
        for (let k = 0; k < 5 && n.parentElement && !label; k++) {
          n = n.parentElement;
          const sp = [...n.querySelectorAll(':scope > span, :scope > label, :scope > div > span, :scope > legend')]
              .map(x => x.innerText.trim()).filter(t => t && t !== e.value && t.length < 40);
          if (sp.length) label = sp[0];
        }
        return {tag: e.tagName, label, value: e.tagName === 'SELECT' ? (e.selectedOptions[0] ? e.selectedOptions[0].text : e.value) : (e.value || ''),
                readonly: !!(e.readOnly || e.disabled)}; })""")


def open_document_page(page: Page, doc_name_pattern: str, page_no: int = 1) -> bool:
    """Clicks the page thumbnail (never the 're-classify' checkbox) of a linked document, e.g. 'Invoice page 1'."""
    import re as _re
    rx = _re.compile(rf"^(?:{doc_name_pattern}) page {page_no}$", _re.IGNORECASE)
    loc = page.get_by_label(rx)
    if loc.count() == 0:
        return False
    loc.first.click()
    page.wait_for_timeout(3500)
    return True
