import csv
import json

from nexus_agent import bugs as B
from nexus_agent.config import Config
from nexus_agent.store import Store
from nexus_agent.testsuite import Case


def setup(tmp_path):
    cfg = Config(root=tmp_path, config_dir=Config().root / "config")
    cfg.settings["bugsheet"]["reported_by"] = "QA"
    return cfg, Store(tmp_path / "state" / "agent.db")


CASE = Case("REG-001", "Consolidated Mapping", "consolidated", "Master + House", "FJ-0000001", "", "", "", "")


def row(result, label, expected, shown, note="", section="Packing List"):
    return {"field": f"{section} · {label}", "section": section, "label": label, "expected_from_document": expected,
            "shown_in_nexus": shown, "result": result, "note": note}


def results():
    return [{"case_id": "REG-001", "ipa": "IPA/1/2026-27", "source": "x.pdf page 7", "verdict": "FAIL", "message": "", "rows": [
        row("PASS", "Packing List No", "9990001 -1", "9990001-1"),
        row("FAIL", "Date", "10 Aug 2026", "9990001 -1, 10 Aug 2026", "the date is right but Nexus adds extra text to the value"),
        row("REVIEW", "Invoice No", "(found on the document)", "9990001 -1", "differs from the Invoice's number"),
        row("INFO", "Supplier No", "", "", "empty in Nexus")]}]


def cands(cfg):
    return B.candidates_from_results(results(), "Packing List", {"REG-001": CASE}, cfg)


def test_only_fail_and_review_become_candidates_with_a_two_line_description(tmp_path):
    cfg, _ = setup(tmp_path)
    c = cands(cfg)
    assert [x["result"] for x in c] == ["FAIL", "REVIEW"]                 # PASS and INFO are not bugs
    lines = B.two_lines(c[0]).split("\n")
    assert len(lines) == 2
    assert "IPA/1/2026-27" in lines[0] and "FJ-0000001" in lines[0] and "REG-001" in lines[0] and "Date" in lines[0]
    assert "`9990001 -1, 10 Aug 2026`" in lines[0] and "`10 Aug 2026`" in lines[1]
    assert B.two_lines(c[1]).startswith("Needs review: ")


def test_recording_saves_candidates_only_and_never_asks_twice(tmp_path):
    cfg, store = setup(tmp_path)
    assert B.record(cfg, store, cands(cfg)) == (2, 0)
    assert B.record(cfg, store, cands(cfg)) == (0, 2)                      # found again: already known, still pending
    assert len(store.bugs_by_status("PENDING")) == 2 and not (cfg.runs_dir / "bugs").exists()   # nothing written anywhere
    assert "Nothing has been added to the bug sheet" in B.summary_line(store, 2, 0)
    fp = cands(cfg)[0]["fingerprint"]
    store.bug_set_status(fp, "NOT_A_BUG", "user")
    assert B.record(cfg, store, cands(cfg)) == (0, 2)                      # a 'not a bug' answer is remembered
    assert [r["fingerprint"] for r in store.bugs_by_status("PENDING")] == [cands(cfg)[1]["fingerprint"]]


def answers(*given):
    it = iter(given)
    return lambda prompt="": next(it)


def test_nothing_is_logged_unless_the_user_answers_y(tmp_path):
    cfg, store = setup(tmp_path)
    B.record(cfg, store, cands(cfg))
    out = []
    counts = B.review(cfg, store, ask=answers("s", "n"), out=out.append)
    assert counts == {"logged": 0, "not_a_bug": 1, "skipped": 1}
    assert not (cfg.runs_dir / "bugs").exists()                            # no paste file, no sheet call
    assert len(store.bugs_by_status("PENDING")) == 1 and len(store.bugs_by_status("NOT_A_BUG")) == 1
    assert not store.bugs_by_status("APPROVED") and not store.bugs_by_status("LOGGED")
    text = "\n".join(out)
    assert "Document says: 10 Aug 2026" in text and "Nexus shows  : 9990001 -1, 10 Aug 2026" in text


def test_quit_stops_and_invalid_answers_are_asked_again(tmp_path):
    cfg, store = setup(tmp_path)
    B.record(cfg, store, cands(cfg))
    counts = B.review(cfg, store, ask=answers("maybe", "", "q"), out=lambda *_: None)
    assert counts == {"logged": 0, "not_a_bug": 0, "skipped": 0} and len(store.bugs_by_status("PENDING")) == 2


def test_y_writes_a_paste_ready_row_in_the_sheet_column_order(tmp_path):
    cfg, store = setup(tmp_path)
    B.record(cfg, store, cands(cfg))
    counts = B.review(cfg, store, ask=answers("y", "s"), out=lambda *_: None)
    assert counts["logged"] == 1 and counts["skipped"] == 1
    assert len(store.bugs_by_status("APPROVED")) == 1                      # confirmed, waiting to be pasted (not 'logged')
    rows = list(csv.reader(open(cfg.runs_dir / "bugs" / "bug_sheet_rows_to_paste.tsv", encoding="utf-8"), delimiter="\t"))
    assert rows[0] == cfg.settings["bugsheet"]["columns"] and len(rows) == 2          # header + exactly the confirmed bug
    d = dict(zip(rows[0], rows[1]))
    assert d["Test Case ID"] == "REG-001" and d["Quadance Job No"] == "FJ-0000001" and d["Nexus Job No"] == "IPA/1/2026-27"
    assert d["Status"] == "Not Taken" and d["Reported By"] == "QA" and "Date" in d and "9990001 -1, 10 Aug 2026" in d["Bug Summary"]


class FakeSheets:
    def __init__(self):
        self.calls = []

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def append(self, **kw):
        self.calls.append(kw)
        return self

    def execute(self):
        return {"updates": {"updatedRange": "'Bugs'!A9:M9"}}


def test_sheets_backend_appends_only_confirmed_bugs(tmp_path):
    cfg, store = setup(tmp_path)
    cfg.settings["bugsheet"].update(backend="sheets", tab_name="Bugs")
    svc = FakeGoogle(cfg.settings["bugsheet"]["columns"], title="Bugs")
    B.record(cfg, store, cands(cfg))
    B.review(cfg, store, ask=answers("n", "y"), out=lambda *_: None, service=svc)
    appends = [c[1] for c in svc.calls if c[0] == "values.append"]
    assert len(appends) == 1                                                 # one 'y' = one row appended; the 'n' added nothing
    call = appends[0]
    assert call["spreadsheetId"] == cfg.settings["bugsheet"]["spreadsheet_id"] and call["range"] == "'Bugs'!A:A"
    assert call["insertDataOption"] == "INSERT_ROWS" and len(call["body"]["values"]) == 1
    assert len(call["body"]["values"][0]) == len(cfg.settings["bugsheet"]["columns"])
    assert len(store.bugs_by_status("LOGGED")) == 1


def test_mapping_failures_and_missing_prealerts_are_candidates_too(tmp_path):
    cfg, _ = setup(tmp_path)
    rows = [{"case_id": "REG-001", "ipa": "IPA/1/2026-27", "nexus_status": "CREATED_IN_NEXUS", "verdict": "FAIL",
             "details": "MASTER: PASS (in Master) | INVOICE: FAIL (found in Master, expected House) | PACKING LIST: FAIL (not found in Nexus)"},
            {"case_id": "REG-001", "ipa": "", "nexus_status": "NOT_RECEIVED", "verdict": "FAIL", "details": "no pre-alert for REG-001 after 420s"}]
    c = B.candidates_from_mapping(rows, {"REG-001": CASE}, cfg)
    assert [x["field"] for x in c] == ["INVOICE", "PACKING LIST", "pre-alert in Nexus"] and all(x["document"] == "Mapping" for x in c)


# --- connecting to the sheet (read-only) --------------------------------------------------------------------
class FakeGoogle:
    """Just enough of the Sheets API: tab list, header row, append. Records every call."""
    def __init__(self, header, gid=11340084, title="UAT Functionality Bugs"):
        self.header, self.gid, self.title, self.calls = header, gid, title, []

    def spreadsheets(self):
        return self

    def get(self, **kw):
        self.calls.append(("spreadsheets.get", kw))
        self._last = "meta"
        return self

    def batchUpdate(self, **kw):
        self.calls.append(("batchUpdate", kw))
        self._last = "append"
        return self

    def values(self):
        outer = self

        class V:
            def get(_s, **kw):
                outer.calls.append(("values.get", kw))
                outer._last = "values"
                return outer

            def append(_s, **kw):
                outer.calls.append(("values.append", kw))
                outer._last = "append"
                return outer
        return V()

    def execute(self):
        if self._last == "meta":
            return {"properties": {"title": "Bug tracker"}, "sheets": [{"properties": {"sheetId": 1, "title": "Other"}},
                                                                      {"properties": {"sheetId": self.gid, "title": self.title}}]}
        if self._last == "values":
            return {"values": [["UAT bug log"], self.header, ["229", "IPA/2150/2026-27", "Air"]]}
        return {"updates": {"updatedRange": f"'{self.title}'!A20:K20"}}


HEADER = ["S.No", "Date Identified", "Module", "Test Case ID", "Quadance Job No", "Nexus Job No", "Bug Description",
          "Expected Result", "Actual Result", "Severity", "Status", "Dev Comments", "Raised By"]


def test_header_names_are_matched_to_fields_and_unknown_columns_stay_empty():
    m = dict(B.suggest_mapping(HEADER))
    assert m["S.No"] == "Bug ID" and m["Date Identified"] == "Date" and m["Bug Description"] == "Bug Summary"
    assert m["Raised By"] == "Reported By" and m["Nexus Job No"] == "Nexus Job No" and m["Dev Comments"] == ""   # never guessed


def test_check_sheet_reads_only_finds_the_tab_by_gid_and_saves_the_mapping(tmp_path):
    cfg, store = setup(tmp_path)
    assert B.effective_backend(cfg) == "paste"                              # not connected yet
    svc = FakeGoogle(HEADER)
    st = B.check_sheet(cfg, svc)
    assert st["tab_name"] == "UAT Functionality Bugs" and st["header"] == HEADER
    assert [c[0] for c in svc.calls] == ["spreadsheets.get", "values.get"]    # reads only, nothing appended
    assert "'UAT Functionality Bugs'!A1:Z6" == svc.calls[1][1]["range"]
    assert B.effective_backend(cfg) == "sheets"                              # connected: confirmed bugs now go to the sheet
    assert (tmp_path / "state" / "bugsheet.json").exists()


def test_after_the_check_a_confirmed_bug_is_one_row_in_the_sheets_own_column_order(tmp_path):
    cfg, store = setup(tmp_path)
    B.check_sheet(cfg, FakeGoogle(HEADER))
    B.record(cfg, store, cands(cfg))
    svc = FakeGoogle(HEADER)
    B.review(cfg, store, ask=answers("y", "n"), out=lambda *_: None, service=svc)
    appends = [c for c in svc.calls if c[0] == "values.append"]
    assert len(appends) == 1                                                 # only the confirmed one
    kw = appends[0][1]
    assert kw["range"] == "'UAT Functionality Bugs'!A:A" and kw["insertDataOption"] == "INSERT_ROWS"
    row = dict(zip(HEADER, kw["body"]["values"][0]))
    assert row["Test Case ID"] == "REG-001" and row["Nexus Job No"] == "IPA/1/2026-27" and row["Raised By"] == "QA"
    assert row["Dev Comments"] == "" and row["S.No"] == "230" and "9990001 -1, 10 Aug 2026" in row["Bug Description"]   # last Sl.no was 229
    assert len(store.bugs_by_status("LOGGED")) == 1 and not (cfg.runs_dir / "bugs").exists()


def test_check_sheet_fails_clearly_when_the_tab_is_not_there(tmp_path):
    cfg, _ = setup(tmp_path)
    try:
        B.check_sheet(cfg, FakeGoogle(HEADER, gid=999))
        raise AssertionError("should have failed")
    except RuntimeError as exc:
        assert "no tab with gid 11340084" in str(exc) and "Other (1)" in str(exc)
    assert B.effective_backend(cfg) == "paste"                               # a failed check does not switch anything on


# --- the sheet's own conventions (columns of the real UAT Functionality Bugs sheet) --------------------------------------
REAL_HEADER = ["Sl.no", "Job Number", "MOT", "File Name", "Bug \u2013 Invoice mapped in House but push fails / skipped", "Priority",
               "Date Reported", "Reported By", "Reported Team", "Status", "Comments", "Assigned To", "Re-test status",
               "Re-test by Dev Team", "Re-test jobs", "Dev Comments"]


def real_cfg(tmp_path):
    cfg, store = setup(tmp_path)
    cfg.settings["bugsheet"].update(reported_by="Vigneshwaran S", backend="sheets", tab_name="UAT Functionality Bugs")
    B.check_sheet(cfg, FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs"))
    return cfg, store


def test_the_real_header_is_mapped_including_the_long_bug_text_column(tmp_path):
    m = dict(B.suggest_mapping(REAL_HEADER))
    assert m["Sl.no"] == "Bug ID" and m["Job Number"] == "Nexus Job No" and m["MOT"] == "MOT" and m["File Name"] == "File Name"
    assert m[REAL_HEADER[4]] == "Bug Summary" and m["Priority"] == "Severity" and m["Date Reported"] == "Date"
    assert m["Reported Team"] == "Reported Team" and m["Comments"] == "" and m["Assigned To"] == ""   # the dev team's columns stay empty


def test_a_new_bug_follows_the_team_format_and_lands_after_the_last_row(tmp_path):
    cfg, store = real_cfg(tmp_path)
    c = dict(cands(cfg)[0], doc_file="FJ-0000001 - Consolidated.pdf")
    rows = B.preview(cfg, [c, dict(c, field="Packing List \u00b7 Other")], FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs"))
    assert [r["row"] for r in rows] == [4, 5]                                  # right after the last used row (FakeGoogle: row 3)
    v = rows[0]["values"]
    assert v["Sl.no"] == "230" and rows[1]["values"]["Sl.no"] == "231"          # next serial numbers after 229
    assert v["Job Number"] == "IPA/1/2026-27" and v["MOT"] == "Air" and v["Reported By"] == "Vigneshwaran S"
    assert v["Reported Team"] == "QA Team" and v["Status"] == "Not Taken" and v["Priority"] == "High"
    assert len(v["Date Reported"]) == 10 and v["Date Reported"][2] == "/" and v["Date Reported"][5] == "/"   # dd/mm/yyyy
    assert v["File Name"].endswith("Doc: FJ-0000001 - Consolidated.pdf") and v["File Name"].startswith("REG-001_IPA-1_Packing-List_")
    assert v["Comments"] == "" and v["Assigned To"] == "" and v["Re-test status"] == "" and v["Dev Comments"] == ""
    text = v[REAL_HEADER[4]]
    assert text.startswith("In the Packing List") and "Expected : `10 Aug 2026`" in text


def test_preview_writes_nothing(tmp_path):
    cfg, store = real_cfg(tmp_path)
    svc = FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    B.preview(cfg, cands(cfg), svc)
    assert not [c for c in svc.calls if c[0] == "values.append"]


def test_the_priority_chosen_for_a_bug_wins_over_the_default(tmp_path):
    cfg, store = real_cfg(tmp_path)
    c = cands(cfg)[0]
    default = B.preview(cfg, [c], FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs"))[0]["values"]["Priority"]
    chosen = B.preview(cfg, [dict(c, severity="Medium")], FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs"))[0]["values"]["Priority"]
    assert default == "High" and chosen == "Medium"


# --- evidence: uploaded to the team's Drive folder and linked as chips like the existing rows ------------------------
class FakeDrive:
    """Files and folders by (parent, name). create() makes ids F1, F2 ... in call order."""
    def __init__(self, existing=None, fail=False, folders=None):
        self.existing, self.fail, self.created = existing or {}, fail, []
        self.folders = dict(folders or {("FOLDER1", "Regression testing"): "RT", ("RT", "Reg - Air & Sea"): "RAS"})
        self._r = ""

    def files(self):
        return self

    def list(self, **kw):
        self.q, self._r = kw["q"], "list"
        return self

    def create(self, **kw):
        if self.fail:
            raise RuntimeError("Drive API has not been used in this project")
        self.created.append(kw["body"])
        self._r = "create"
        return self

    def execute(self):
        if self._r == "list":
            parts = self.q.split("'")
            name, parent = parts[1], parts[3]
            if "mimeType" in self.q:
                fid = self.folders.get((parent, name))
            else:
                fid = self.existing.get(name)
            return {"files": [{"id": fid, "name": name}] if fid else []}
        body = self.created[-1]
        if body.get("mimeType"):
            fid = f"DIR{len([b for b in self.created if b.get('mimeType')])}"
            self.folders[(body["parents"][0], body["name"])] = fid
            return {"id": fid}
        return {"id": f"ID{len([b for b in self.created if not b.get('mimeType')])}"}


def evidence_setup(tmp_path):
    cfg, store = real_cfg(tmp_path)
    cfg.settings["bugsheet"]["evidence_folder_id"] = "FOLDER1"
    cfg.settings["bugsheet"]["evidence_path"] = ["Regression testing", "Reg - Air & Sea", "{date}"]
    c = dict(cands(cfg)[0], doc_file="FJ-0000001 - Consolidated.pdf", ipa="IPA/1/2026-27")
    shot = tmp_path / "runs" / "2026-10-24" / "REG-001" / "packing_data.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    c["evidence"] = str(shot)
    pdf = tmp_path / "samples" / "REG-001" / c["doc_file"]
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF")
    return cfg, store, c


def test_evidence_and_source_pdf_are_uploaded_to_todays_folder_and_linked_as_chips(tmp_path):
    from datetime import datetime
    cfg, store, c = evidence_setup(tmp_path)
    drive, sheets = FakeDrive(), FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    msg = B.attach_evidence(cfg, c, 230, sheets=sheets, drive=drive)
    today = datetime.now().strftime("%d-%m-%Y")
    assert drive.folders[("RAS", today)] == "DIR1"                                          # today's folder was created like the team's
    files = [(f["name"], f["parents"]) for f in drive.created if not f.get("mimeType")]
    assert files == [(B.evidence_name(c), ["DIR1"]), ("FJ-0000001 - Consolidated.pdf", ["DIR1"])]
    req = [x for x in sheets.calls if x[0] == "batchUpdate"][0][1]
    cell = req["body"]["requests"][0]["updateCells"]
    assert cell["start"] == {"sheetId": 11340084, "rowIndex": 229, "columnIndex": 3}          # row 230, the File Name column
    v = cell["rows"][0]["values"][0]
    assert v["userEnteredValue"]["stringValue"] == "@\nDoc: @"                               # one '@' placeholder per chip (API rule)
    assert v["chipRuns"] == [{"chip": {"richLinkProperties": {"uri": "https://drive.google.com/file/d/ID1/view"}}},
                             {"startIndex": 7, "chip": {"richLinkProperties": {"uri": "https://drive.google.com/file/d/ID2/view"}}}]
    assert cell["fields"] == "userEnteredValue,chipRuns" and "linked as chips" in msg
    assert v["chipRuns"][1]["startIndex"] == v["userEnteredValue"]["stringValue"].rindex("@")


def test_an_existing_date_folder_is_reused(tmp_path):
    from datetime import datetime
    cfg, store, c = evidence_setup(tmp_path)
    drive = FakeDrive(folders={("FOLDER1", "Regression testing"): "RT", ("RT", "Reg - Air & Sea"): "RAS",
                               ("RAS", datetime.now().strftime("%d-%m-%Y")): "TODAY"})
    B.attach_evidence(cfg, c, 230, sheets=FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs"), drive=drive)
    assert not [f for f in drive.created if f.get("mimeType")]                              # no folder created
    assert all(f["parents"] == ["TODAY"] for f in drive.created)


def test_a_file_already_in_the_folder_is_reused_not_uploaded_twice(tmp_path):
    cfg, store, c = evidence_setup(tmp_path)
    drive = FakeDrive(existing={"FJ-0000001 - Consolidated.pdf": "OLDPDF"})
    sheets = FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    B.attach_evidence(cfg, c, 230, sheets=sheets, drive=drive)
    assert [f["name"] for f in drive.created if not f.get("mimeType")] == [B.evidence_name(c)]    # only the screenshot is new
    runs = [x for x in sheets.calls if x[0] == "batchUpdate"][0][1]["body"]["requests"][0]["updateCells"]["rows"][0]["values"][0]["chipRuns"]
    assert runs[1]["chip"]["richLinkProperties"]["uri"].endswith("/OLDPDF/view")


def test_without_a_folder_the_row_is_left_alone(tmp_path):
    cfg, store, c = evidence_setup(tmp_path)
    cfg.settings["bugsheet"]["evidence_folder_id"] = ""
    sheets = FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    assert "no evidence folder" in B.attach_evidence(cfg, c, 230, sheets=sheets, drive=FakeDrive())
    assert not [x for x in sheets.calls if x[0] == "batchUpdate"]


def test_a_drive_problem_never_loses_the_bug(tmp_path):
    cfg, store, c = evidence_setup(tmp_path)
    B.record(cfg, store, [c])
    sheets = FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    msg = B.log_confirmed(cfg, store, c, service=sheets, drive=FakeDrive(fail=True))
    assert "added to the bug sheet" in msg and "evidence NOT linked" in msg
    assert len([x for x in sheets.calls if x[0] == "values.append"]) == 1 and len(store.bugs_by_status("LOGGED")) == 1


def test_a_status_chosen_for_a_bug_wins_over_the_default(tmp_path):
    cfg, store = real_cfg(tmp_path)
    c = cands(cfg)[0]
    svc = FakeGoogle(REAL_HEADER, title="UAT Functionality Bugs")
    assert B.preview(cfg, [c], svc)[0]["values"]["Status"] == "Not Taken"
    assert B.preview(cfg, [dict(c, status="Discussion needed")], svc)[0]["values"]["Status"] == "Discussion needed"


def test_baseline_marks_decided_findings_known(tmp_path):
    from nexus_agent import baseline as BL
    from nexus_agent.bugs import fingerprint
    from nexus_agent.store import Store
    st = Store(tmp_path / "a.db")
    fp = fingerprint("REG-9", "House", "Cargo · Pieces", "1", "1PALLET")
    st.bug_add_pending(fp, "REG-9", "House", "Cargo · Pieces", "{}")
    st.bug_set_status(fp, "LOGGED", "row 5")
    rows = [{"field": "Cargo · Pieces", "expected_from_document": "1", "shown_in_nexus": "1PALLET", "result": "FAIL", "note": ""},
            {"field": "Cargo · Gross", "expected_from_document": "5", "shown_in_nexus": "6", "result": "FAIL", "note": ""}]
    res = [{"case_id": "REG-9", "ipa": "x", "verdict": "FAIL", "rows": rows}]
    BL.apply_checks(st, res, "House")
    assert rows[0]["result"] == "KNOWN" and rows[1]["result"] == "FAIL" and res[0]["verdict"] == "FAIL"
    rows[1]["result"] = "PASS"
    BL.apply_checks(st, res, "House")
    assert res[0]["verdict"] == "PASS"


def test_history_counts_repeats_per_prealert(tmp_path):
    from nexus_agent import history as H
    from nexus_agent.store import Store
    st = Store(tmp_path / "h.db")
    assert st.history_add("fp1", "IPA/1", "REG-1", "House", "Pieces")
    assert not st.history_add("fp1", "IPA/1", "REG-1", "House", "Pieces")      # same pre-alert checked again: not a repeat
    assert st.history_add("fp1", "IPA/2", "REG-1", "House", "Pieces")          # new pre-alert: it came back
    st.history_add("fp2", "IPA/2", "REG-1", "House", "Gross")
    d = H.build(st)
    assert d["items"][0]["count"] == 2 and len(d["items"]) == 2 and d["occurrences"] == 3
