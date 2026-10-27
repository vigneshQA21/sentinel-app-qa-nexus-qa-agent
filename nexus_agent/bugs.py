"""Bug candidates: every FAIL / REVIEW found by the checks becomes a candidate, saved locally. NOTHING is added to the bug
sheet unless the user confirms that bug in `./nx bugs`. 'Not a bug' answers are remembered so they are never asked again."""
from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from .config import Config
from .store import Store
from .testsuite import Case

DOC_TITLES = {"MASTER": "Master", "HOUSE": "House", "MANIFEST": "Manifest", "INVOICE": "Invoice", "PACKING": "Packing List",
              "DEBITNOTE": "Debit Note", "SHIPPERDOC": "Shipper Document",
              "MAPPING": "Mapping"}
EVIDENCE_FILE = {"Master": "master_data.png", "House": "house_data.png", "Manifest": "manifest_data.png",
                 "Invoice": "invoice_data.png", "Packing List": "packing_data.png", "Debit Note": "debitnote_data.png",
                 "Shipper Document": "shipperdoc_data.png", "Mapping": "list.png"}


def fingerprint(case_id: str, document: str, field: str, expected: str, shown: str) -> str:
    key = "|".join(re.sub(r"\s+", " ", x or "").strip().upper() for x in (case_id, document, field, expected, shown))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _short(text: str, n: int = 90) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n].rstrip() + " ..."


def two_lines(c: dict) -> str:
    """The bug in two lines: where it is and what Nexus shows, then what was expected."""
    if c.get("description"):                      # a bug that spans several documents is written by hand
        return c["description"]
    tag = "Needs review: " if c["result"] == "REVIEW" else ""
    l1 = (f"{tag}Nexus job {c['ipa'] or '(unknown)'} (Quadance {c['fj'] or '(unknown)'}, {c['case_id']}), {c['document']}, "
          f"field {c['field']}: Nexus shows `{_short(c['shown'])}`.")
    if c["expected"] and not c["expected"].startswith("("):
        l2 = f"Expected `{_short(c['expected'])}`, as printed on the document."
    else:
        l2 = "Expected the value printed on the document."
    note = (c["note"] or "").strip()
    return f"{l1}\n{l2}" + (f" {note[0].upper() + note[1:]}." if note else "")


def candidates_from_results(results: list[dict], title: str, cases: dict[str, Case], cfg: Config) -> list[dict]:
    """results = master / house / docs check results (each with rows). title = Master | House | Manifest | Invoice | Packing List."""
    out = []
    for r in results:
        case = cases.get(r["case_id"])
        evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / r["case_id"] / EVIDENCE_FILE.get(title, "")
        for x in r.get("rows") or []:
            if x["result"] not in ("FAIL", "REVIEW"):
                continue
            exp = " ".join(x["expected_from_document"].split())
            shown = " ".join(x["shown_in_nexus"].split())
            field = x["field"] if x.get("section") else x["field"]
            out.append({"case_id": r["case_id"], "fj": (case.sample_ref if case else "") or "", "ipa": r.get("ipa", ""),
                        "doc_file": re.sub(r" page [\d-]+$", "", r.get("source", "") or ""),
                        "document": title, "field": field, "expected": exp, "shown": shown, "result": x["result"],
                        "note": x.get("note", ""), "evidence": str(evidence) if evidence.name and evidence.exists() else "",
                        "fingerprint": fingerprint(r["case_id"], title, field, exp, shown)})
    return out


def candidates_from_mapping(rows: list[dict], cases: dict[str, Case], cfg: Config) -> list[dict]:
    """rows = results of `validate` (the Master/House/Manifest/Invoice/Packing List placement check)."""
    out = []
    for r in rows:
        if r.get("verdict") != "FAIL" and r.get("nexus_status") != "NOT_RECEIVED":
            continue
        case = cases.get(r["case_id"])
        evidence = cfg.runs_dir / datetime.now().strftime("%Y-%m-%d") / r["case_id"] / "list.png"
        parts = [p for p in (r.get("details") or "").split(" | ") if ": FAIL" in p or "not found" in p.lower() or "after" in p.lower()]
        for part in parts or [r.get("details", "")]:
            field = part.split(":")[0] if ": FAIL" in part else "pre-alert in Nexus"
            out.append({"case_id": r["case_id"], "fj": (case.sample_ref if case else "") or "", "ipa": r.get("ipa", ""),
                        "document": "Mapping", "field": field, "expected": "(document linked under the right parent)",
                        "shown": part, "result": "FAIL", "note": "", "evidence": str(evidence) if evidence.exists() else "",
                        "fingerprint": fingerprint(r["case_id"], "Mapping", field, "", part)})
    return out


def record(cfg: Config, store: Store, candidates: list[dict]) -> tuple[int, int]:
    """Saves the candidates as PENDING. Returns (new, already known). Writes nothing anywhere else."""
    new = 0
    for c in candidates:
        store.history_add(c["fingerprint"], c.get("ipa", ""), c["case_id"], c["document"], c["field"])
        if store.bug_add_pending(c["fingerprint"], c["case_id"], c["document"], c["field"], json.dumps(c)):
            new += 1
    return new, len(candidates) - new


def summary_line(store: Store, new: int, known: int) -> str:
    pending = len(store.bugs_by_status("PENDING"))
    if not new and not known:
        return ""
    return (f"\nBUG CANDIDATES: {new} new, {known} already known | {pending} waiting for your decision.\n"
            f"Nothing has been added to the bug sheet. Review them with:  ./nx bugs")


# --- the sheet row ----------------------------------------------------------------------------------------
SYNONYMS = {   # sheet header (letters and digits only, lower case) -> the field it holds
    "Bug ID": ["bugid", "id", "sno", "slno", "srno", "bugno", "defectid"],
    "Date": ["date", "reporteddate", "datereported", "dateraised", "raisedon", "loggeddate", "dateidentified", "identifiedon"],
    "MOT": ["mot", "modeoftransport"],
    "File Name": ["filename", "files", "recording", "video"],
    "Reported Team": ["reportedteam", "team", "raisedteam"],
    "Module": ["module", "feature", "area", "component", "functionality", "screen"],
    "Test Case ID": ["testcaseid", "tcid", "testcase", "scenarioid", "testid", "testcaseno"],
    "Quadance Job No": ["quadancejobno", "quadancejob", "quadancejobnumber", "fjnumber", "fjno", "fjjobno", "fjjob", "quadanceno"],
    "Nexus Job No": ["nexusjobno", "nexusjob", "nexusjobnumber", "ipanumber", "ipano", "ipa", "jobno", "jobnumber", "nexusno"],
    "Bug Summary": ["bugsummary", "summary", "description", "bugdescription", "title", "issue", "observation", "bugtitle", "issuedescription"],
    "Expected Result": ["expectedresult", "expected", "expectedbehaviour", "expectedbehavior"],
    "Actual Result": ["actualresult", "actual", "actualbehaviour", "actualbehavior"],
    "Severity": ["severity", "priority"],
    "Status": ["status", "bugstatus", "state"],
    "Evidence": ["evidence", "screenshot", "screenshots", "attachment", "attachments", "link", "proof"],
    "Reported By": ["reportedby", "raisedby", "reporter", "tester", "loggedby", "owner", "identifiedby"],
}


def suggest_mapping(header: list[str]) -> list[tuple[str, str]]:
    """[(sheet header, field or '')] by matching the header text; unknown headers stay empty (never guessed)."""
    out = []
    for h in header:
        key = re.sub(r"[^a-z0-9]", "", h.lower())
        field = next((f for f, syn in SYNONYMS.items() if key in syn), "")
        if not field and key.startswith("bug") and key not in ("bugid", "bugno"):
            field = "Bug Summary"            # this sheet's bug-text column has a long, changing header that starts with "Bug"
        out.append((h, field))
    return out


def state_file(cfg: Config) -> Path:
    return cfg.state_dir / "bugsheet.json"


def sheet_state(cfg: Config) -> dict:
    """What `./nx bugs --check-sheet` learned about the sheet (tab title, header, column mapping), if it has run."""
    f = state_file(cfg)
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def effective_backend(cfg: Config) -> str:
    be = cfg.settings["bugsheet"].get("backend", "auto")
    return ("sheets" if sheet_state(cfg).get("verified") else "paste") if be == "auto" else be


GOOGLE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]


def google_creds(cfg: Config):
    """Credentials for the bug sheet (Sheets) and the evidence folder (Drive). Saved locally in secrets/ (git-ignored)."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    bs = cfg.settings["bugsheet"]
    token = cfg.path(bs["token_file"])
    creds = Credentials.from_authorized_user_file(str(token), GOOGLE_SCOPES) if token.exists() else None
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds = InstalledAppFlow.from_client_secrets_file(str(cfg.path(cfg.settings["gmail"]["credentials_file"])), GOOGLE_SCOPES).run_local_server(port=0)
        token.parent.mkdir(parents=True, exist_ok=True)
        token.write_text(creds.to_json(), encoding="utf-8")
    return creds


def sheets_service(cfg: Config):
    from googleapiclient.discovery import build
    return build("sheets", "v4", credentials=google_creds(cfg), cache_discovery=False)


def drive_service(cfg: Config):
    from googleapiclient.discovery import build
    return build("drive", "v3", credentials=google_creds(cfg), cache_discovery=False)


# --- evidence: files go to the team's Drive folder and are linked as chips, exactly like the existing rows ------------------
def drive_upload(drive, path: Path, folder_id: str, name: str | None = None) -> tuple[str, str]:
    """Uploads a file into the evidence folder (or reuses the file with the same name that is already there).
    Returns (file id, link). Nothing is ever overwritten or deleted."""
    from googleapiclient.http import MediaFileUpload
    name = name or path.name
    q = "name = '{}' and '{}' in parents and trashed = false".format(name.replace("\\", "\\\\").replace("'", "\\'"), folder_id)
    found = drive.files().list(q=q, fields="files(id,name)", pageSize=1, supportsAllDrives=True,
                               includeItemsFromAllDrives=True).execute().get("files", [])
    if found:
        fid = found[0]["id"]
    else:
        fid = drive.files().create(body={"name": name, "parents": [folder_id]}, media_body=MediaFileUpload(str(path)),
                                   fields="id", supportsAllDrives=True).execute()["id"]
    return fid, f"https://drive.google.com/file/d/{fid}/view"


def file_chips_request(sheet_id: int, row_no: int, col_index: int, ev_url: str, doc_url: str = "") -> dict:
    """batchUpdate request that writes the File Name cell the way the team has it: [evidence chip] newline 'Doc: ' [pdf chip].
    When writing, every chip is ONE '@' placeholder character in the text and only the chipped runs are listed; Google shows the
    chip with the Drive file's own name (the file names are the evidence name and the PDF name)."""
    text = "@" + ("\nDoc: @" if doc_url else "")
    runs = [{"chip": {"richLinkProperties": {"uri": ev_url}}}]
    if doc_url:
        runs.append({"startIndex": text.rindex("@"), "chip": {"richLinkProperties": {"uri": doc_url}}})
    return {"updateCells": {"rows": [{"values": [{"userEnteredValue": {"stringValue": text}, "chipRuns": runs}]}],
                            "fields": "userEnteredValue,chipRuns",
                            "start": {"sheetId": sheet_id, "rowIndex": row_no - 1, "columnIndex": col_index}}}


FOLDER = "application/vnd.google-apps.folder"


def _q(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def ensure_folder_path(drive, root_id: str, parts: list[str]) -> str:
    """Finds (or creates, like the team's own dated folders) root/part1/part2/... and returns the last folder's id."""
    parent = root_id
    for name in parts:
        q = f"name = '{_q(name)}' and '{parent}' in parents and trashed = false and mimeType = '{FOLDER}'"
        found = drive.files().list(q=q, fields="files(id,name)", pageSize=1, supportsAllDrives=True,
                                   includeItemsFromAllDrives=True).execute().get("files", [])
        parent = found[0]["id"] if found else drive.files().create(
            body={"name": name, "parents": [parent], "mimeType": FOLDER}, fields="id", supportsAllDrives=True).execute()["id"]
    return parent


def evidence_folder(cfg: Config, drive) -> str:
    """Where this suite's evidence goes: <evidence_folder_id>/<evidence_path ...>, with {date} = today as dd-mm-yyyy like the
    team's folders ('Regression testing' > 'Reg - Air & Sea' > '24-10-2026')."""
    bs = cfg.settings["bugsheet"]
    parts = [p.format(date=datetime.now().strftime("%d-%m-%Y")) for p in bs.get("evidence_path", [])]
    return ensure_folder_path(drive, bs["evidence_folder_id"], parts)


def discover_evidence_folder(cfg: Config, sheets=None, drive=None) -> list[tuple[str, str, int]]:
    """READ-ONLY, best effort: the Drive folders that hold the evidence files already linked as chips in the sheet's last rows.
    Returns [(folder id, folder name, number of files)] most used first."""
    bs = cfg.settings["bugsheet"]
    st = sheet_state(cfg)
    sheets, drive = sheets or sheets_service(cfg), drive or drive_service(cfg)
    last = read_sheet_tail(cfg, sheets, n=1)["last_row"]
    col = st["header"].index(next(h for h, f in st["mapping"] if f == "File Name"))
    letter = chr(ord("A") + col)
    res = sheets.spreadsheets().get(spreadsheetId=bs["spreadsheet_id"], ranges=[f"'{st['tab_name']}'!{letter}{max(2, last - 12)}:{letter}{last}"],
                                    includeGridData=True, fields="sheets.data.rowData.values(chipRuns)").execute()
    ids = []
    for row in res["sheets"][0]["data"][0].get("rowData", []):
        for cell in row.get("values", []):
            for run in cell.get("chipRuns", []) or []:
                m = re.search(r"/d/([\w-]+)", run.get("chip", {}).get("richLinkProperties", {}).get("uri", "") or "")
                if m:
                    ids.append(m.group(1))
    counts: dict[str, int] = {}
    for fid in dict.fromkeys(ids):
        try:
            for parent in drive.files().get(fileId=fid, fields="parents", supportsAllDrives=True).execute().get("parents", []):
                counts[parent] = counts.get(parent, 0) + 1
        except Exception:
            continue
    out = []
    for pid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        try:
            name = drive.files().get(fileId=pid, fields="name", supportsAllDrives=True).execute().get("name", "")
        except Exception:
            name = ""
        out.append((pid, name, n))
    return out


def attach_evidence(cfg: Config, c: dict, row_no: int, sheets=None, drive=None) -> str:
    """Uploads the bug's screenshot and its source PDF to the evidence folder and turns the File Name cell of `row_no` into chips.
    Only that one cell is changed. Returns what happened."""
    bs = cfg.settings["bugsheet"]
    folder = bs.get("evidence_folder_id")
    if not folder:
        return "no evidence folder set (bugsheet.evidence_folder_id): the File Name stays plain text"
    shot = copy_evidence(cfg, c)
    if shot is None:
        return "no screenshot found for this bug: the File Name stays plain text"
    drive = drive or drive_service(cfg)
    sheets = sheets or sheets_service(cfg)
    folder = evidence_folder(cfg, drive)
    _fid, ev_url = drive_upload(drive, shot, folder, evidence_name(c))
    doc_name, doc_url = "", ""
    pdf = cfg.path(cfg.settings["testsuite"]["samples_dir"]) / c["case_id"] / (c.get("doc_file") or "")
    if c.get("doc_file") and pdf.exists():
        _fid2, doc_url = drive_upload(drive, pdf, folder, c["doc_file"])
        doc_name = c["doc_file"]
    col = sheet_state(cfg)["header"].index(next(h for h, f in sheet_state(cfg)["mapping"] if f == "File Name"))
    sheets.spreadsheets().batchUpdate(spreadsheetId=bs["spreadsheet_id"], body={"requests": [
        file_chips_request(int(bs["tab_gid"]), row_no, col, ev_url, doc_url)]}).execute()
    return f"evidence uploaded and linked as chips ({evidence_name(c)}" + (f" + {doc_name})" if doc_name else ")")


def check_sheet(cfg: Config, service=None) -> dict:
    """Connects to the bug sheet READ-ONLY: finds the tab from its gid, reads the header row, proposes the column mapping and saves it
    in state/bugsheet.json. Writes nothing to the sheet."""
    bs = cfg.settings["bugsheet"]
    service = service or sheets_service(cfg)
    meta = service.spreadsheets().get(spreadsheetId=bs["spreadsheet_id"], fields="properties.title,sheets.properties").execute()
    tabs = [t["properties"] for t in meta.get("sheets", [])]
    tab = next((t for t in tabs if str(t.get("sheetId")) == str(bs.get("tab_gid"))), None)
    if tab is None:
        raise RuntimeError(f"no tab with gid {bs.get('tab_gid')} in the sheet. Tabs: " + ", ".join(f"{t['title']} ({t['sheetId']})" for t in tabs))
    values = service.spreadsheets().values().get(spreadsheetId=bs["spreadsheet_id"], range=f"'{tab['title']}'!A1:Z6").execute().get("values", [])
    header = next((r for r in values if sum(1 for c in r if str(c).strip()) >= 3), values[0] if values else [])
    header = [str(h).strip() for h in header]
    mapping = suggest_mapping(header)
    state = {"verified": True, "spreadsheet_title": meta.get("properties", {}).get("title", ""), "tab_name": tab["title"],
             "header": header, "mapping": mapping, "checked_at": datetime.now().isoformat(timespec="seconds")}
    state_file(cfg).parent.mkdir(parents=True, exist_ok=True)
    state_file(cfg).write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    return state


def read_sheet_tail(cfg: Config, service=None, n: int = 6) -> dict:
    """READ-ONLY. The sheet's header row, how many rows it has, and its last n non-empty rows (to copy the way bugs are recorded)."""
    bs = cfg.settings["bugsheet"]
    st = sheet_state(cfg)
    tab = st.get("tab_name") or bs.get("tab_name")
    service = service or sheets_service(cfg)
    rows = service.spreadsheets().values().get(spreadsheetId=bs["spreadsheet_id"], range=f"'{tab}'!A1:Z").execute().get("values", [])
    filled = [(i + 1, r) for i, r in enumerate(rows) if any(str(c).strip() for c in r)]
    head_no = next((i for i, r in filled if sum(1 for c in r if str(c).strip()) >= 3), 1)
    data = [(i, r) for i, r in filled if i > head_no]
    return {"tab": tab, "header_row": head_no, "last_row": filled[-1][0] if filled else 0, "data_rows": len(data), "tail": data[-n:]}


def evidence_name(c: dict) -> str:
    """A descriptive file name for the screenshot, e.g. REG-001_IPA-2144_Packing-List_Date.png"""
    ipa = re.sub(r"/20\d\d-\d\d$", "", c["ipa"] or "job").replace("/", "-")
    parts = [x.strip() for x in c["field"].split("\u00b7")]
    label = re.sub(r"[^A-Za-z0-9]+", "-", " ".join(parts[-2:] if len(parts) >= 2 and parts[-2] != c["document"] else parts[-1:])).strip("-")
    return f"{c['case_id']}_{ipa}_{re.sub(r'[^A-Za-z0-9]+', '-', c['document']).strip('-')}_{label}.png"


def sheet_description(c: dict) -> str:
    """The bug text in the way the team writes it: what Nexus shows, then 'Expected : ...'."""
    if c.get("description"):
        return c["description"]
    parts = [x.strip() for x in c["field"].split("\u00b7")]
    label = f"{parts[0]} {parts[1]}" if len(parts) == 2 and parts[0] != c["document"] else parts[-1]
    exp = f"Expected : `{_short(c['expected'])}`, as printed on the document." if c["expected"] and not c["expected"].startswith("(") \
        else "Expected : the value printed on the document."
    note = (c["note"] or "").strip()
    return f"In the {c['document']}, the {label} field shows `{_short(c['shown'])}`. {exp}" + (f" {note[0].upper() + note[1:]}." if note else "")


def copy_evidence(cfg: Config, c: dict) -> Path | None:
    """Copies the bug's screenshot to runs/evidence/<the file name written in the sheet>, so the name in the row exists."""
    src = Path(c["evidence"]) if c.get("evidence") else None
    if not src or not src.exists():
        return None
    dest = cfg.runs_dir / "evidence" / evidence_name(c)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return dest


def _values(cfg: Config, c: dict) -> dict:
    bs = cfg.settings["bugsheet"]
    doc = f" Doc: {c['doc_file']}" if c.get("doc_file") else ""
    values = {"Date": datetime.now().strftime(bs.get("date_format", "%d/%m/%Y")), "Module": f"Nexus - {c['document']}",
              "Test Case ID": c["case_id"], "Quadance Job No": c["fj"], "Nexus Job No": c["ipa"], "Document": c["document"],
              "Field": c["field"], "Bug Summary": sheet_description(c), "Expected Result": c["expected"], "Actual Result": c["shown"],
              "Result": c["result"], "Note": c["note"], "Evidence": c["evidence"], "File Name": f"{evidence_name(c)}{doc}",
              "Reported By": bs.get("reported_by", ""), "Bug ID": ""}
    values.update({k: v for k, v in (bs.get("defaults") or {}).items() if k not in values or not values[k]})
    if c.get("severity"):                       # the priority the user chose for this bug wins over the default
        values["Severity"] = c["severity"]
    if c.get("status"):                         # e.g. "Discussion needed" while the PO decides
        values["Status"] = c["status"]
    return values


def next_serial(cfg: Config, service=None) -> tuple[int, int]:
    """(next Sl.no, row number the new row will land in): one after the last used row. READ-ONLY."""
    tail = read_sheet_tail(cfg, service, n=1)
    last = tail["tail"][-1][1] if tail["tail"] else []
    try:
        no = int(str(last[0]).strip()) + 1
    except (IndexError, ValueError):
        no = tail["data_rows"] + 1
    return no, tail["last_row"] + 1


def preview(cfg: Config, cands: list[dict], service=None) -> list[dict]:
    """The exact rows that would be appended, and where. Writes nothing."""
    no, row_no = next_serial(cfg, service)
    return [{"row": row_no + i, "values": dict(zip(header_of(cfg), sheet_row(cfg, c, no + i)))} for i, c in enumerate(cands)]


def header_of(cfg: Config) -> list[str]:
    st = sheet_state(cfg)
    return st["header"] if st.get("header") else cfg.settings["bugsheet"]["columns"]


def sheet_row(cfg: Config, c: dict, serial: int | None = None) -> list[str]:
    """One row in the sheet's own column order. After --check-sheet the real header is used; unknown columns stay empty."""
    values, st = _values(cfg, c), sheet_state(cfg)
    if serial is not None:
        values["Bug ID"] = str(serial)
    if st.get("mapping"):
        return [values.get(field, "") if field else "" for _h, field in st["mapping"]]
    return [values.get(col, "") for col in cfg.settings["bugsheet"]["columns"]]


def write_paste_file(cfg: Config, rows: list[list[str]]) -> Path:
    out = cfg.runs_dir / "bugs"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "bug_sheet_rows_to_paste.tsv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter="\t")
        if new:
            w.writerow(header_of(cfg))
        w.writerows(rows)
    return path


def sheets_append(cfg: Config, rows: list[list[str]], service=None) -> str:
    """Appends rows to the bug sheet with the Google Sheets API. `service` lets tests inject a fake."""
    bs = cfg.settings["bugsheet"]
    tab = sheet_state(cfg).get("tab_name") or bs.get("tab_name")
    if not tab:
        raise RuntimeError("the bug sheet's tab is not known yet: run  ./nx bugs --check-sheet  first")
    service = service or sheets_service(cfg)
    resp = service.spreadsheets().values().append(
        spreadsheetId=bs["spreadsheet_id"], range=f"'{tab}'!A:A", valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS", body={"values": rows}).execute()
    return resp.get("updates", {}).get("updatedRange", "appended")


def log_confirmed(cfg: Config, store: Store, c: dict, service=None, drive=None) -> str:
    """Called ONLY after the user typed 'y' for this bug. Returns what happened."""
    if effective_backend(cfg) == "sheets":
        service = service or sheets_service(cfg)
        copy_evidence(cfg, c)
        no, _ = next_serial(cfg, service)
        where = sheets_append(cfg, [sheet_row(cfg, c, no)], service)
        store.bug_set_status(c["fingerprint"], "LOGGED", where)
        msg = f"added to the bug sheet ({where})"
        m = re.search(r"!A(\d+):", where)
        if m:                                         # the bug is saved first; evidence problems never lose it
            try:
                msg += "; " + attach_evidence(cfg, c, int(m.group(1)), sheets=service, drive=drive)
            except Exception as exc:
                msg += f"; evidence NOT linked ({type(exc).__name__}: {str(exc).splitlines()[0][:120]})"
        return msg
    path = write_paste_file(cfg, [sheet_row(cfg, c)])
    store.bug_set_status(c["fingerprint"], "APPROVED", str(path))
    return f"confirmed; the row is in {path} - paste it into the bug sheet"


def review(cfg: Config, store: Store, ask=input, out=print, service=None, include_all: bool = False, drive=None) -> dict:
    """Walks through the pending candidates, one at a time, and asks. y = log it, n = not a bug (remembered), s = skip, q = stop."""
    counts = {"logged": 0, "not_a_bug": 0, "skipped": 0}
    pending = store.bugs_by_status("PENDING")
    if not pending:
        out("No bug candidates are waiting for a decision.")
        return counts
    out(f"{len(pending)} bug candidate(s) waiting. Nothing is added unless you answer y.\n")
    for n, rec in enumerate(pending, 1):
        c = json.loads(rec["data"])
        out(f"BUG CANDIDATE {n} of {len(pending)}   [{c['result']}]   {c['case_id']} · Quadance {c['fj']} · Nexus {c['ipa']}")
        out(f"  Document     : {c['document']}")
        out(f"  Field        : {c['field']}")
        out(f"  Document says: {c['expected']}")
        out(f"  Nexus shows  : {c['shown']}")
        if c["note"]:
            out(f"  Note         : {c['note']}")
        if c["evidence"]:
            out(f"  Screenshot   : {c['evidence']}")
        out("  Two-line bug :\n    " + two_lines(c).replace("\n", "\n    "))
        while True:
            ans = ask("  Add this to the UAT bug sheet?  [y] yes   [n] not a bug   [s] skip for now   [q] quit : ").strip().lower()
            if ans in ("y", "n", "s", "q"):
                break
        if ans == "q":
            break
        if ans == "y":
            out("  -> " + log_confirmed(cfg, store, c, service, drive))
            counts["logged"] += 1
        elif ans == "n":
            store.bug_set_status(c["fingerprint"], "NOT_A_BUG", "marked by the user")
            out("  -> marked as not a bug; it will not be asked again")
            counts["not_a_bug"] += 1
        else:
            counts["skipped"] += 1
        out("")
    return counts
