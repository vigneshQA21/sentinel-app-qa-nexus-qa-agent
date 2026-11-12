"""Manifest-first scenarios: after ONLY the Manifest of a sample was sent, Nexus builds a Master draft (Master bill number) and one House
draft per house (house bill numbers) from it. This reads the 'Shipment Details' lines of the pre-alert in the UI and compares the
numbers with the ones printed in the documents (settings: air_manifest_scenarios.cases)."""
from __future__ import annotations

import csv
import logging
import re
from datetime import datetime
from pathlib import Path

from .config import Config
from .nexus.session import NexusSession
from .nexus.uat import UatPages

log = logging.getLogger(__name__)


def _n(v: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (v or "").upper())


def compare(case_id: str, ipa: str, expected: dict, lines: list[dict]) -> list[dict]:
    """One row per check: Master draft present + number, House drafts count + each number, anything unexpected."""
    rows = []

    def row(check, exp, act, ok, note=""):
        rows.append({"case_id": case_id, "ipa": ipa, "check": check, "expected": exp, "actual": act,
                     "result": "PASS" if ok else "FAIL", "note": note})

    masters = [x for x in lines if x.get("Record Type", "").lower().startswith("master")]
    houses = [x for x in lines if x.get("Record Type", "").lower().startswith("house")]
    row("Master draft exists", "1", str(len(masters)), len(masters) == 1)
    if masters:
        act = masters[0].get("Bill No.", "")
        row("Master draft number", expected["master"], act, _n(act) == _n(expected["master"]),
            "" if _n(act) == _n(expected["master"]) else "the Master number printed in the Manifest is not the one in the draft")
        row("Master draft type", "Master draft", masters[0].get("Record Type", ""), masters[0].get("Record Type", "").lower() == "master draft")
    row("House drafts count", str(len(expected["houses"])), str(len(houses)), len(houses) == len(expected["houses"]))
    got = [h.get("Bill No.", "") for h in houses]
    for h in expected["houses"]:
        hit = next((g for g in got if _n(g) == _n(h)), None)
        row(f"House draft number {h}", h, hit or ", ".join(got) or "(none)", hit is not None,
            "" if hit else "no House draft carries this house number")
    for g in got:
        if not any(_n(g) == _n(h) for h in expected["houses"]):
            row("Unexpected House draft", "(none)", g, False, "a House draft whose number is not printed in the Manifest")
    return rows


def run(cfg: Config, case_ids: list[str]) -> list[dict]:
    sc = cfg.settings["air_manifest_scenarios"]["cases"]
    day = datetime.now().strftime("%Y-%m-%d")
    out: list[dict] = []
    with NexusSession(cfg, headless=False) as s:
        ui = UatPages(s.page, cfg)
        for cid in case_ids:
            if cid not in sc:
                log.warning("%s is not an air manifest scenario", cid)
                continue
            ui.case_dir = cfg.runs_dir / day / cid
            ui.case_dir.mkdir(parents=True, exist_ok=True)
            ui.open_list()
            s.page.wait_for_timeout(2500)
            cells = ui.case_cells(f"{cid} |")
            if not cells:
                out.append({"case_id": cid, "ipa": "", "check": "Pre-alert found in Nexus", "expected": "1", "actual": "0",
                            "result": "FAIL", "note": "no pre-alert with this case id in the Pre-Alerts tab (not created yet, or deleted)"})
                continue
            ipa = ui.row_info(cells[0]).get("ipa", "")
            ui.expand_row(cells[0])
            s.page.wait_for_timeout(1500)
            lines = ui.read_shipment_details()
            ui.screenshot(ui.case_dir / f"drafts_{ipa.replace('/', '-')}_expanded.png")
            out += compare(cid, ipa, sc[cid], lines)
            out.append({"case_id": cid, "ipa": ipa, "check": "Draft lines as shown in Nexus", "expected": "",
                        "actual": " | ".join(f"{x.get('Record Type','')}: {x.get('Bill No.','')} ({x.get('Shipper','') or 'no shipper'}; "
                                             f"{x.get('Status','')})" for x in lines), "result": "INFO", "note": ""})
    return out


def write_report(cfg: Config, rows: list[dict]) -> Path:
    d = cfg.runs_dir / "_reports"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"drafts_data_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["case_id", "ipa", "check", "expected", "actual", "result", "note"])
        w.writeheader()
        w.writerows(rows)
    return path


def report(rows: list[dict]) -> str:
    lines = []
    for cid in dict.fromkeys(r["case_id"] for r in rows):
        mine = [r for r in rows if r["case_id"] == cid]
        bad = [r for r in mine if r["result"] == "FAIL"]
        lines.append(f"{cid}  {'FAIL' if bad else 'PASS'}  {mine[0]['ipa']}")
        for r in mine:
            if r["result"] != "INFO":
                lines.append(f"    {r['result']:5} {r['check']:30} expected {r['expected']:14} Nexus {r['actual']}" + (f"   [{r['note']}]" if r["note"] else ""))
            else:
                lines.append(f"    Nexus lines: {r['actual']}")
    return "\n".join(lines)
