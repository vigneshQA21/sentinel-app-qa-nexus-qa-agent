"""Deletes the agent's own regression pre-alerts in Nexus on the user's command (`./nx delete SEA-REG-001`).

What is deleted: every pre-alert row (Pre-Alerts tab AND Others tab: follow-up emails of individual-mapping cases) whose subject
STARTS with '<CASE-ID> |' and carries the agent's tag ('QA agent trigger'). Nothing else is ever touched (other testers' pre-alerts of the
same shipment stay: the user deletes those). The row's '...' menu > Delete is used, exactly as a person would; a screenshot of every row is kept
before it is deleted. Afterwards the case can be sent again without --resend."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .config import Config
from .master_check import norm
from .nexus.session import NexusSession, SessionExpired
from .nexus.uat import UatPages
from .pdf_split import page_texts_layout
from .store import Store
from .testsuite import sample_files

log = logging.getLogger(__name__)
CASE_ID = re.compile(r"^(SEA-)?REG-\d{3}$")
IPA_ID = re.compile(r"^IPA/\d+/\d{4}-\d{2}$", re.IGNORECASE)
TAG = "QA agent trigger"
GROUPS = {"AIR-DAILY": ["REG-001", "REG-002", "REG-005", "REG-009", "REG-006", "REG-007"],
          "SEA-DAILY": [f"SEA-REG-{i:03d}" for i in range(1, 10)]}


def expand(names: list[str]) -> list[str]:
    out: list[str] = []
    for n in names:
        n = n.strip().upper()
        out += GROUPS.get(n) or [n]
    bad = [c for c in out if not CASE_ID.match(c) and not IPA_ID.match(c)]
    if bad:
        raise ValueError(f"not a regression case id: {', '.join(bad)} (expected REG-nnn or SEA-REG-nnn, or air-daily / sea-daily)")
    return list(dict.fromkeys(out))


def is_ours(subject: str, case_id: str) -> bool:
    """Starts with '<CASE-ID> |' (so 'REG-001 |' never matches 'SEA-REG-001 |') and carries the agent's tag."""
    s = " ".join(subject.split())
    return s.upper().startswith(f"{case_id} |") and TAG.lower() in s.lower()


def _row_of(cell):
    node = cell
    for _ in range(14):
        node = node.locator("xpath=..")
        t = node.inner_text()
        if re.search(r"IPA/\d+/\d{4}-\d{2}", t):            # Others rows have no progress bar: the id is enough
            return node
    return None


def _full_row(cell):
    """The whole list row (id, subject, sender, received date): the first ancestor whose text holds a sender mail id."""
    node = cell
    for _ in range(14):
        node = node.locator("xpath=..")
        if re.search(r"[\w.+-]+@[\w.-]+", node.inner_text()):
            return node
    return None


def _rows(ui: UatPages, case_id: str) -> list[dict]:
    """The subject cells of this case in the tab that is open now: [{cell, ipa, subject}] (only the agent's own rows)."""
    out = []
    cells = ui.page.locator(ui.u["subject_cell"].format(token=f"{case_id} |"))
    for i in range(cells.count()):
        c = cells.nth(i)
        subject = c.inner_text()
        if not is_ours(subject, case_id):
            continue
        row = _row_of(c)
        ipa = ""
        if row is not None:
            m = re.search(r"IPA/\d+/\d{4}-\d{2}", row.inner_text())
            ipa = m.group(0) if m else ""
        out.append({"cell": c, "ipa": ipa, "subject": " ".join(subject.split())})
    return out


def _open_menu(ui: UatPages, cell) -> bool:
    pg = ui.page
    box = cell.bounding_box()
    if not box:
        return False
    vw = pg.viewport_size["width"]
    for dx in (48, 30, 66, 84):                                # the three dots sit at the right end of the row; the exact x differs a little per tab
        pg.mouse.click(vw - dx, box["y"] + box["height"] / 2)
        pg.wait_for_timeout(700)
        if pg.get_by_text("View Email", exact=True).count():
            return True
        pg.keyboard.press("Escape")
    return False


def _confirm(ui: UatPages, shot: Path, ipa: str, case_id: str = "") -> str:
    """After 'Delete' was chosen the 'Delete job' dialog names the job. Confirm only when it names THIS job and this case, else Cancel."""
    pg = ui.page
    para = pg.get_by_text(re.compile(r"Delete this job", re.I)).first
    try:
        para.wait_for(state="visible", timeout=6000)
    except Exception:
        raise RuntimeError("no 'Delete job' confirmation dialog appeared (screenshot saved)")
    text = " ".join(para.inner_text().split())
    ui.screenshot(shot)
    if (ipa and ipa not in text) or (case_id and f"{case_id} |" not in text.upper()):
        pg.get_by_role("button", name=re.compile(r"^\s*cancel\s*$", re.I)).first.click()
        raise RuntimeError(f"the dialog names a different job, cancelled: {text[:110]}")
    pg.get_by_role("button", name=re.compile(r"^\s*delete job\s*$", re.I)).last.click()
    pg.wait_for_timeout(2500)
    return "confirmed in the 'Delete job' dialog"


def sample_text(cfg: Config, case_id: str) -> str:
    """Normalised text of the case's sample PDF(s): a pre-alert belongs to the case only when its bill number is printed here."""
    out = []
    for f in [x for x in sample_files(cfg, SimpleNamespace(id=case_id)) if x.suffix.lower() == ".pdf"]:
        try:
            data = f.read_bytes()
            texts = page_texts_layout(data, ocr=False)
            if any(len(t.strip()) < 25 for t in texts):
                texts = page_texts_layout(data, ocr=True)
            out.append(norm("\n".join(texts)))
        except Exception as exc:
            log.warning("could not read %s: %s", f.name, exc)
    return "\n".join(out)


def _bills_file(cfg: Config) -> Path:
    return cfg.state_dir / "case_bills.json"


def known_bills(cfg: Config, case_id: str) -> list[str]:
    try:
        return json.loads(_bills_file(cfg).read_text()).get(case_id, [])
    except Exception:
        return []


def remember_bills(cfg: Config, case_id: str, bills: list[str]) -> None:
    """The Master/House bill numbers Nexus showed for the case's own pre-alert: kept so a later delete can find other rows of the same shipment."""
    try:
        data = json.loads(_bills_file(cfg).read_text())
    except Exception:
        data = {}
    data[case_id] = sorted(set(data.get(case_id, [])) | set(bills))
    _bills_file(cfg).write_text(json.dumps(data, indent=1))


def row_meta(row) -> dict:
    """IPA id, subject, sender and received date/time of a list row."""
    t = row.inner_text()
    lines = [l.strip() for l in t.splitlines() if l.strip()]
    ipa = next((l for l in lines if re.fullmatch(r"IPA/\d+/\d{4}-\d{2}", l)), "")
    subject = lines[lines.index(ipa) + 1] if ipa and lines.index(ipa) + 1 < len(lines) else ""
    mail = re.search(r"[\w.+-]+@[\w.-]+", t)
    when = re.search(r"\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}(?::\d{2})?\s*[AP]?M?", t)
    return {"ipa": ipa, "subject": " ".join(subject.split()), "from": mail.group(0) if mail else "?", "received": when.group(0).strip() if when else "?"}


def row_bills(ui: UatPages, cell) -> list[str]:
    """Master/House bill numbers of the expanded pre-alert row ([] when the row shows no Shipment Details)."""
    try:
        ui.expand_row(cell)
        return [r["Bill No."].strip() for r in ui.read_shipment_details() if r.get("Bill No.", "").strip()]
    except Exception:
        return []


def search_terms(ui: UatPages, terms: list[tuple[str, str]]) -> list[dict]:
    """The list's own search, both tabs, for every (filter, text) pair, e.g. ('Bill No', 'TAOJAI26165972') or ('Email Subject', 'FJ-0000723').
    The page is loaded and the filter chosen once per filter. Returns [{tab, ipa, subject, from, received, term}]."""
    pg = ui.page
    out: list[dict] = []
    for mode in dict.fromkeys(m for m, _ in terms):
        ui.open_list()
        if mode != "ID":                                          # 'ID' is the list's default filter
            pg.get_by_text("ID", exact=True).first.click()
            pg.get_by_text(mode, exact=True).first.click()
        box = pg.get_by_placeholder("Search").first
        for _m, term in [t for t in terms if t[0] == mode]:
            for tab in ("Pre-Alerts", "Others"):
                pg.get_by_text(f"{tab} (", exact=False).first.click()
                pg.wait_for_timeout(600)
                box.fill(""); box.fill(term)                     # the filter has to be typed again after a tab change, else Others lists every row
                pg.wait_for_timeout(2500)
                seen = set()
                cells = pg.locator(ui.u["row_marker"])
                for i in range(cells.count()):
                    row = _full_row(cells.nth(i))
                    m = row_meta(row) if row is not None else {}
                    if m.get("ipa") and m["ipa"] not in seen:
                        seen.add(m["ipa"]); out.append({**m, "tab": tab, "term": term, "bill": term})
                log.info("%s search %s in %s: %d row(s) %s", mode, term, tab, len(seen), sorted(seen))
        for tab in ("Others", "Pre-Alerts"):                    # leave BOTH tabs unfiltered: a stuck filter makes the next list load hang
            pg.get_by_text(f"{tab} (", exact=False).first.click()
            pg.wait_for_timeout(500)
            box.fill("")
            pg.wait_for_timeout(1500)
        pg.keyboard.press("Escape")
    return out


def search_bills(ui: UatPages, bills: list[str]) -> list[dict]:
    return search_terms(ui, [("Bill No", b) for b in bills])


def plan_case(ui: UatPages, cfg: Config, case_id: str, extra_bills: list[str], sender: str = "") -> dict:
    """Decides what is safe to delete. A row is the case's own when its subject starts with '<CASE> |' AND (when the sample text is readable
    and the row's bills are readable) one of its bills is printed in the sample. Everything else on the same bill number, or with the case's
    subject but other bills, is NOT deleted: it is returned as `review` for the user to confirm by hand."""
    text = sample_text(cfg, case_id)
    own, review, bills = [], [], set(extra_bills) | set(known_bills(cfg, case_id))
    for tab in ("Pre-Alerts", "Others"):
        ui.open_list()
        if tab == "Others":
            ui.page.get_by_text("Others (", exact=False).first.click(); ui.page.wait_for_timeout(3500)
        for r in _rows(ui, case_id):
            row = _full_row(r["cell"])
            meta = row_meta(row) if row is not None else {"ipa": r["ipa"], "subject": r["subject"], "from": "?", "received": "?"}   # read before the row is expanded
            b = row_bills(ui, r["cell"]) if tab == "Pre-Alerts" else []
            if sender and meta["from"].lower() != sender.lower():
                review.append({**meta, "tab": tab, "bill": ", ".join(b), "why": f"subject matches the case, but it was sent from {meta['from']}, not {sender}"})
            elif text and b and not any(norm(x) in text for x in b):
                review.append({**meta, "tab": tab, "bill": ", ".join(b), "why": "subject matches the case, but its bill number is not in the case's sample document"})
            else:
                own.append(r["ipa"]); bills |= set(b)
    if bills:
        remember_bills(cfg, case_id, sorted(bills))
    for m in search_bills(ui, sorted(bills)):
        if m["ipa"] not in own and all(x["ipa"] != m["ipa"] for x in review):
            review.append({**m, "why": f"carries bill {m['bill']} of this case, but its subject is not '{case_id} | ... QA agent trigger'"})
    return {"own": own, "review": review, "bills": sorted(bills), "excluded": {x["ipa"] for x in review}}


def delete_ipa(ui: UatPages, ipa: str, evidence: Path, dry_run: bool = False) -> list[dict]:
    """Deletes ONE pre-alert named by its IPA id (an approved row that is not the agent's own). The 'Delete job' dialog must name this IPA, else Cancel."""
    for tab in ("Pre-Alerts", "Others"):
        ui.open_list()
        if tab == "Others":
            ui.page.get_by_text("Others (", exact=False).first.click(); ui.page.wait_for_timeout(3500)
        ui.page.mouse.move(5, 5)
        cell = ui.page.get_by_text(ipa, exact=True)
        if not cell.count():
            continue
        rec = {"tab": tab, "ipa": ipa, "subject": "", "result": ""}
        row = _full_row(cell.first)
        rec["subject"] = row_meta(row)["subject"] if row is not None else ""
        if dry_run:
            rec["result"] = "would delete"; return [rec]
        ui.screenshot(evidence / f"{datetime.now():%H%M%S}_{tab}_{ipa.replace('/', '-')}_before_delete.png")
        try:
            if not _open_menu(ui, cell.first):
                raise RuntimeError("could not open the row menu")
            menu = ui.page.get_by_text("Delete", exact=True)
            if not menu.count():
                raise RuntimeError("the row menu has no Delete option")
            menu.last.click()
            how = _confirm(ui, evidence / f"{datetime.now():%H%M%S}_{ipa.replace('/', '-')}_confirm_dialog.png", ipa)
            ui.open_list()
            if tab == "Others":
                ui.page.get_by_text("Others (", exact=False).first.click(); ui.page.wait_for_timeout(3500)
            gone = not ui.page.get_by_text(ipa, exact=True).count()
            rec["result"] = f"deleted ({how})" if gone else f"FAILED: {how}, but the row is still listed"
        except Exception as exc:
            rec["result"] = f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:140]}"
            ui.screenshot(evidence / f"{datetime.now():%H%M%S}_failed.png")
        return [rec]
    return [{"tab": "-", "ipa": ipa, "subject": "", "result": "not found in Nexus"}]


def counts(ui: UatPages) -> str:
    """'Pre-Alerts 180, Others 252': the tab counts, to show whether Nexus removed more than the rows listed (it also removes related follow-up jobs)."""
    t = ui.page.locator("body").inner_text()
    pa, ot = re.search(r"Pre-Alerts \((\d+)\)", t), re.search(r"Others \((\d+)\)", t)
    return f"Pre-Alerts {pa.group(1) if pa else '?'}, Others {ot.group(1) if ot else '?'}"


def delete_case(ui: UatPages, case_id: str, evidence: Path, dry_run: bool, excluded: set | None = None) -> list[dict]:
    """Deletes every row of the case in Pre-Alerts and in Others. Returns one dict per row: {tab, ipa, subject, result}."""
    results: list[dict] = []
    for tab in ("Pre-Alerts", "Others"):
        rows = None                                            # rows read after the previous delete (same page): no reload needed
        for attempt in range(30):                              # the list re-renders after each delete: look again, take the first row
            if rows is None:
                ui.open_list()
                if tab == "Others":
                    ui.page.get_by_text("Others (", exact=False).first.click()
                    ui.page.wait_for_timeout(3500)
                ui.page.mouse.move(5, 5)
                rows = [x for x in _rows(ui, case_id) if x["ipa"] not in (excluded or set())]
            if dry_run:
                results += [{"tab": tab, "ipa": r["ipa"], "subject": r["subject"], "result": "would delete"} for r in rows]
                break
            if not rows:
                break
            r = rows[0]; rows = None
            rec = {"tab": tab, "ipa": r["ipa"], "subject": r["subject"], "result": ""}
            results.append(rec)
            ui.screenshot(evidence / f"{datetime.now():%H%M%S}_{tab}_{(r['ipa'] or 'row').replace('/', '-')}_before_delete.png")
            try:
                if not _open_menu(ui, r["cell"]):
                    raise RuntimeError("could not open the row menu")
                menu = ui.page.get_by_text("Delete", exact=True)
                if not menu.count():
                    raise RuntimeError("the row menu has no Delete option")
                menu.last.click()
                how = _confirm(ui, evidence / f"{datetime.now():%H%M%S}_{(r['ipa'] or 'row').replace('/', '-')}_confirm_dialog.png", r['ipa'], case_id)
                ui.open_list()
                if tab == "Others":
                    ui.page.get_by_text("Others (", exact=False).first.click(); ui.page.wait_for_timeout(3500)
                left = _rows(ui, case_id)
                gone = not any(x["ipa"] == r["ipa"] and r["ipa"] for x in left)
                rows = [x for x in left if x["ipa"] not in (excluded or set())]        # the next row to delete, no further reload
                rec["result"] = f"deleted ({how})" if gone else f"FAILED: {how}, but the row is still listed"
                if not gone:
                    break
            except Exception as exc:
                rec["result"] = f"FAILED: {type(exc).__name__}: {str(exc).splitlines()[0][:140]}"
                ui.screenshot(evidence / f"{datetime.now():%H%M%S}_failed.png")
                break
    return results


def report_review(case_id: str, plan: dict, out=print) -> None:
    out(f"{case_id}: bill numbers of this case: {', '.join(plan['bills']) or 'none known (no own pre-alert row to read them from; pass --bill)'}")
    if not plan["review"]:
        return
    out(f"{case_id}: NOT deleted, needs your confirmation ({len(plan['review'])}):")
    for r in plan["review"]:
        out(f"    {r['tab']:10} {r['ipa']:18} subject: {r['subject']}\n"
            f"               from: {r['from']}   received: {r['received']}   bill: {r['bill']}\n"
            f"               why: {r['why']}")


def sample_refs(cfg: Config, case_id: str) -> list[str]:
    """FJ references printed in the file names of the case's sample(s): other testers name their jobs after them ('Retest - 231 -FJ-0000723')."""
    pat = cfg.settings["references"]["job_pattern"]
    refs = []
    for f in sample_files(cfg, SimpleNamespace(id=case_id)):
        m = re.search(pat, f.stem, re.IGNORECASE)
        if m and m.group(1).upper() not in refs:
            refs.append(m.group(1).upper())
    for c in (cfg.settings.get("testsuite", {}).get("extra_cases") or []):      # an extra case's own reference (e.g. a Master number when no FJ exists)
        if c.get("id") == case_id and c.get("sample_ref") and str(c["sample_ref"]).upper() not in refs:
            refs.append(str(c["sample_ref"]).upper())
    return refs


def sample_bill_numbers(cfg: Config, case_id: str) -> list[str]:
    """Bill numbers of the case: those Nexus showed for it before (state/case_bills.json) plus the HAWBs read from an Air sample."""
    bills = list(known_bills(cfg, case_id))
    sc = (cfg.settings.get("air_manifest_scenarios", {}).get("cases") or {}).get(case_id) or {}
    for b in [sc.get("master")] + list(sc.get("houses") or []):               # numbers listed for an air manifest scenario
        if b and b not in bills:
            bills.append(b)
    if not case_id.upper().startswith("SEA-"):
        try:
            from .pdf_split import detect_parts, find_hawbs, page_texts
            for f in [x for x in sample_files(cfg, SimpleNamespace(id=case_id)) if x.suffix.lower() == ".pdf"]:
                texts = page_texts(f.read_bytes())
                for h in find_hawbs(texts, detect_parts(texts, cfg.settings["pdf_split"]["keywords"]), cfg):
                    if h not in bills:
                        bills.append(h)
        except Exception as exc:
            log.warning("could not read the HAWB of %s: %s", case_id, exc)
    return bills


def recent_ipas(cfg: Config, case_id: str, limit: int = 4) -> list[str]:
    """IPA ids this case had in Nexus on earlier runs (the validation reports and the bug history): the second look-up of the pre-send check."""
    ipas: list[str] = []
    try:
        import csv
        for f in sorted((cfg.runs_dir / "_reports").glob("validate_*.csv"), reverse=True)[:60]:
            for r in csv.DictReader(open(f, encoding="utf-8")):
                if r.get("case_id") == case_id and re.match(r"^IPA/\d+/", r.get("ipa") or "") and r["ipa"] not in ipas:
                    ipas.append(r["ipa"])
            if len(ipas) >= limit:
                break
    except Exception as exc:
        log.warning("could not read earlier IPA ids of %s: %s", case_id, exc)
    return ipas[:limit]


def preflight(cfg: Config, case_ids: list[str], headless: bool = False, out=print) -> dict[str, list[dict]]:
    """Standing order: before sending, look the case's bill numbers and FJ reference up in Nexus (Bill No and Email Subject search, Pre-Alerts and
    Others). Returns {case: rows that already exist}; an empty list means the sample is not in Nexus and the case can be sent."""
    result: dict[str, list[dict]] = {}
    with NexusSession(cfg, headless=headless) as sess:
        sess.ensure_logged_in()
        ui = UatPages(sess.page, cfg)
        for case_id in case_ids:
            bills, refs = sample_bill_numbers(cfg, case_id), sample_refs(cfg, case_id)
            ipas = recent_ipas(cfg, case_id)
            terms = [("Bill No", b) for b in bills] + [("ID", i) for i in ipas] + [("Email Subject", r) for r in refs]   # 1) bill number, 2) IPA number, then the FJ reference
            rows = search_terms(ui, terms) if terms else []
            uniq: dict[str, dict] = {}
            for r in rows:
                u = uniq.setdefault(r["ipa"], {**r, "terms": []})
                u["terms"].append(r["term"])
            found = list(uniq.values())
            # a row reached ONLY through an old IPA id that is another regression case's row (e.g. 'SEA-REG-002 |' for REG-002) is not this sample
            other_case = re.compile(r"^(SEA-)?REG-\d{3} \|")
            found = [r for r in found if not (set(t_ for t_ in r["terms"]) <= set(ipas) and other_case.match(r["subject"]) and not is_ours(r["subject"], case_id))]
            for r in found:
                r["own"] = is_ours(r["subject"], case_id)
            result[case_id] = found
            looked = ", ".join(bills + ipas + refs) or "nothing to search for"
            if not found:
                out(f"{case_id}: CLEAR - not in Nexus (searched {looked}); it can be sent.")
            else:
                out(f"{case_id}: BLOCKED - {len(found)} row(s) of this sample exist in Nexus (searched {looked}); NOT sent. Confirm manually which to delete:")
                for r in found:
                    who = "the agent's own row: ./nx delete " + case_id if r["own"] else "NOT the agent's: delete only if you name it"
                    out(f"    {r['tab']:10} {r['ipa']:18} subject: {r['subject']}\n"
                        f"               from: {r['from']}   received: {r['received']}   matched: {', '.join(dict.fromkeys(r['terms']))}   ({who})")
    return result


def run(cfg: Config, names: list[str], dry_run: bool = False, headless: bool = False, out=print, bills: list[str] | None = None, sender: str = "") -> int:
    cases = expand(names)
    store = Store(cfg.state_dir / "agent.db")
    failed = False
    try:
        with NexusSession(cfg, headless=headless) as sess:
            sess.ensure_logged_in()
            ui = UatPages(sess.page, cfg)
            for case_id in [c for c in cases if IPA_ID.match(c)]:                       # an approved row, named by its IPA id
                ev = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / "_deleted_by_ipa"
                ev.mkdir(parents=True, exist_ok=True)
                for r in delete_ipa(ui, case_id, ev, dry_run):
                    out(f"{case_id}: {r['tab']:10} {r['result']}   {r['subject'][:70]}")
                    failed |= r["result"].startswith("FAILED")
            for case_id in [c for c in cases if not IPA_ID.match(c)]:
                evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / case_id / "cleanup"
                evidence.mkdir(parents=True, exist_ok=True)
                ui.open_list(); before = counts(ui)
                plan = plan_case(ui, cfg, case_id, bills or [], sender)
                report_review(case_id, plan, out)
                res = delete_case(ui, case_id, evidence, dry_run, plan["excluded"])
                if not res:
                    out(f"{case_id}: nothing to delete in Nexus" + (f" (but {len(plan['review'])} row(s) were left for your confirmation)" if plan["review"] else ""))
                for r in res:
                    out(f"{case_id}: {r['tab']:10} {r['ipa'] or '(no id)':18} {r['result']}   {r['subject'][:70]}")
                    failed |= r["result"].startswith("FAILED")
                if res and not dry_run:
                    ui.open_list(); out(f"{case_id}: tab counts {before}  ->  {counts(ui)}  (Nexus also removes related follow-up jobs of the same thread)")
                if plan["review"] and not dry_run:
                    out(f"{case_id}: NOT ready to send again: {len(plan['review'])} row(s) of this shipment are still in Nexus (a new email would be absorbed into them)")
                elif not dry_run and not any(r["result"].startswith("FAILED") for r in res):
                    n = store.forget_sent(case_id)
                    out(f"{case_id}: ready to send again without --resend" + (f" ({n} sent-file records cleared)" if n else ""))
    except SessionExpired as exc:
        out(str(exc)); return 2
    return 1 if failed else 0
