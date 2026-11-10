# Execute commands (no Claude needed)

Complete list of every command and flag: [docs/COMMANDS.md](../docs/COMMANDS.md). Zoho daily update: `./nx post-update --file state/zoho_update.md`.

Always start from the project folder. `./nx` and `./run_regression.sh` always use the project's own Python, so they work
from any terminal. **Whatever you run is really sent** (a preview needs `--dry-run`).

```bash
cd /home/unifo/Downloads/nexus_agent
```

## Most used (the daily routine)
```bash
./run_regression.sh REG-001 --validate    # 1. THE full run: send -> wait for Nexus -> mapping check -> Master, House, Manifest, Invoice, Packing List data checks (every field printed) -> bug candidates
./nx validate-master                      # 2. Re-check the Master data of what is ALREADY in Nexus (no send). Defaults to REG-001
./nx validate-house                       #    ... the House data
./nx validate-docs                        #    ... Manifest, Invoice and Packing List (add --only invoice to check one)
./nx validate                             #    ... the mapping (which document sits under Master / House / Manifest)
./nx bugs                                 # 3. Decide on the bug candidates: y = add to the UAT bug sheet, n = not a bug, s = skip
./nx history                              #    Internal bug history: bugs found, how often each came back (per pre-alert), status, sheet row
./nx casedoc                              #    Write every validation of REG-001/REG-002 into a new tab of the test-case Excel (backup first)
./nx log "what we changed or decided"     # 4. Add a note to today's entry in docs/PROGRESS_LOG.md
./nx login                                # 5. Nexus session expired: log in by hand once (log in, then close the window)
./run_regression.sh REG-001               #    Send only, no UI check
```
**Before every run:** delete the old pre-alerts of that case in Nexus. Otherwise the new email is linked to the old
pre-alert and lands in *Others* as a duplicate. (Nothing is deleted automatically yet.)

## What `./run_regression.sh <CASE> --validate` does (time counted from sending, T)
| When | What |
|---|---|
| T+0:00 | the case's emails are sent (the Nexus login is checked first; if it expired, nothing is sent) |
| T+3:00 | buffer over: first look in Nexus (countdown printed meanwhile) |
| T+3:00 to T+7:00 | polls every 20 s until the pre-alert appears and its job progress is 100% |
| then | **mapping check**, then the **Master, House, Manifest, Invoice and Packing List data checks**: every field is printed as `field : value` with the count and compared with the source PDF |
| at the end | the FAIL/REVIEW findings are saved as **bug candidates** ("BUG CANDIDATES: n new ... Review them with ./nx bugs") |
| T+7:00 | still nothing in Nexus: the case is reported NOT_RECEIVED |

The browser is always visible. Several cases: each is sent, validated, then the next one is sent.
Timing is in `config/settings.yaml` -> `validation:` (`initial_wait_seconds`, `poll_seconds`, `max_wait_seconds`).

## Bugs and the Google sheet (nothing is added without your y)
```bash
./nx bugs --list          # only list the candidates (nothing is asked, nothing is written)
./nx bugs                 # one by one: shows what the document says, what Nexus shows, the screenshot and the two-line bug
                          #   [y] add to the UAT bug sheet   [n] not a bug (remembered, never asked again)   [s] skip for now   [q] quit
./nx bugs --check-sheet   # read-only: connects to the sheet and Drive, shows the tab, the columns and how they are filled,
                          #   and whether the evidence folder accepts files. Run it after any Google change.
```
What a **y** does (backend `auto` = Google sheet once `--check-sheet` has succeeded, otherwise a paste file):
1. Adds one row at the **end** of the *UAT Functionality Bugs* tab, in the team's format: next Sl.no, Nexus job (IPA), MOT, File Name, bug text, Priority, Date `dd/mm/yyyy`, Reported By, QA Team, Status. Existing rows are never changed.
2. Uploads the screenshot and the source PDF to Drive: `UAT Bugs > Regression testing > Reg - Air & Sea > <dd-mm-yyyy>` (today's folder is created if missing) and writes the **File Name cell as two chips** (evidence, then `Doc:` and the PDF), like the team's own rows.
3. If Drive fails, the bug row is still saved and the message says "evidence NOT linked".

Priority and status default to `High` / `Not Taken`; to log with another value (for example Medium and *Discussion needed*), say so and the agent sets it for that bug.
Settings: `config/settings.yaml` -> `bugsheet:` (`spreadsheet_id`, `tab_gid`, `evidence_folder_id`, `evidence_path`, `reported_by`, `defaults`, `backend`).

### One-time Google setup (already done on 2026-10-24)
1. In the Google Cloud project: enable the **Google Sheets API** and the **Google Drive API**.
2. Run `./nx bugs --check-sheet` and click **Allow** (one login covers Sheets and Drive; saved in `secrets/google_bugs_token.json`).
3. The Google account needs edit access to the bug sheet and the evidence folder.

### If something goes wrong
| Message | What to do |
|---|---|
| `Nothing was sent. Nexus session expired ...` | `./nx login`, log in, close the window, run again |
| `Google Sheets API has not been used in project ...` (403) | Enable the Sheets API (or the Drive API) in the Cloud console, wait 2 minutes, run `./nx bugs --check-sheet` |
| `NO permission to add files to it` | Give the Google account edit access to the evidence folder |
| `evidence NOT linked` | The bug row is saved; check Drive access, then tell the agent to attach the evidence |
| `no pre-alert for REG-001 in Nexus` | Not there after 7 minutes, or it went to the *Others* tab as a duplicate: delete the old pre-alert first |
| Differences that look odd | Someone may have edited the pre-alert in Nexus after it was created; re-run on a fresh one |

## Several cases / the daily tag AIR_SINGLE_HOUSE_DAILY (15 emails)
```bash
./run_regression.sh REG-001 REG-002 --validate     # per case: send -> validate -> next
./run_regression.sh air-daily --validate           # REG-001, 002, 005, 009 validated (006, 007 are sent; their UI checks are not built yet)
./run_regression.sh air-daily                      # send only, 5-minute gap between cases
```
Cases with samples: REG-001, 002, 005, 006, 007, 009. REG-003 is excluded (same shipment as REG-007); REG-016 is a hypothetical case with no sample (not executable). REG-011 uses a sample split from FJ-0001012 plus a dummy unclassified document (its own shipment, no collision with other cases): `./run_regression.sh REG-011 --validate`.

## Known-issue baseline and bug history
- A finding that is already logged in the bug sheet (or marked "not a bug") is shown as **KNOWN**: visible, but it does not fail the case. Only NEW differences fail. If a logged bug's field matches the document again, the run prints "possibly FIXED".
- Every finding is also counted in the **bug history** (one occurrence per Nexus pre-alert; re-checking the same pre-alert is not a repeat). `./nx history` shows the totals, the bugs that came back and how many times.
- `./nx casedoc` writes the full validation list (mapping + every field, expected, last result, baseline, bug-sheet row) into the tab "Validations REG-001 & REG-002" of `Air_Single_House_Daily_Regression.xlsx`.

## Screenshots (every check, nothing overwritten)
- Every check saves the **Pre-Alerts page** (`prealerts_list.png`) and the **expanded row** with Shipment Details (`prealert_expanded.png`), plus the viewer and data screenshots, in `runs/<date>/<case>/`.
- Each screenshot is also copied to `runs/<date>/<case>/archive/<run time>_<IPA>_<name>.png`, so a later run never overwrites an earlier one (e.g. a pre-alert you delete afterwards).

## Trace of every check (pick the exact screenshot for a bug) and root cause
- Each check writes ONE trace per case and pre-alert: `runs/<date>/<case>/trace_<run time>_<IPA>/` with the screenshots numbered in the order they were taken (Pre-Alerts page, row expanded, each viewer parent with Unmatched/Unclassified open, each other linked document opened in the viewer such as SHIPPERDOC and DELIVERYNOTE, the row's "Unresolved Documents" block when it has one, the Others tab, then the data panels) and an **`index.html`** that shows them all with captions. Open the index in a browser.
- The index starts with **Probable root cause**, and the mapping report prints the same lines (`PROBABLE ROOT CAUSE: ...`): wrong house number read by Nexus, documents left Unmatched, a Master received as its own pre-alert, follow-ups in the Others tab, a document not classified anywhere. They are hints for the tester, not a verdict.
- A document counts as Unmatched only if it is linked under no parent (a parent's Unmatched list repeats documents linked elsewhere).

## Scanned documents (OCR)
- A page without a text layer (a scan) is read with OCR when it is CHECKED (never when sending): the right orientation is found, the text is cached in `state/ocr_cache/` (first read ~10 s per page, then instant).
- Every value Nexus shows is looked up in the OCR text (dates printed as `08AUG`, units printed as `K`, numbers, 75% of the words of a name or address). Found = PASS; not found = **REVIEW** ("look at the scan by eye"). OCR can misread characters, so a scan never produces a FAIL or a bug candidate on its own.
- Documents a case does not list (e.g. no Invoice in REG-009) are skipped instead of reported as errors.

## Where to look afterwards
| What | Where |
|---|---|
| Send report | `runs/_reports/suite_<time>.csv` |
| Mapping report | `runs/_reports/validate_<time>.csv` |
| Data reports (every field, expected vs Nexus) | `runs/_reports/master_data_`, `house_data_`, `manifest_data_`, `invoice_data_`, `packing_data_<time>.csv` |
| Screenshots | `runs/<date>/<case>/` (copies named for the bug in `runs/evidence/`) |
| What was sent | Gmail Sent, search `"Regression testing"` |
| What we did and what is next | `docs/PROGRESS_LOG.md` |

## Flags (`run_regression.sh`)
| Flag | Meaning |
|---|---|
| `--validate` | after each case is sent: buffer, polling, mapping check and the five data checks (headed) |
| `--no-wait` | no 5-minute gap between cases (send only; `--validate` spaces cases itself) |
| `--no-force` | skip cases that fail screening (REG-002 and REG-009 would be skipped) |
| `--dry-run` | preview only, sends nothing |

`./nx validate`, `validate-master`, `validate-house` and `validate-docs` also take `--cases REG-002 ...`, `--wait <seconds>` and `--headless`.

## Occasionally
```bash
./nx cases                                   # list the cases and how many samples each has
./nx ingest                                  # file downloads from samples/_inbox/ under their case
.venv/bin/python scripts/check_session.py    # LOGGED IN / SESSION EXPIRED (Nexus)
.venv/bin/python -m pytest -q                # run the tests (86)
```

## Good to know
- The data checks treat the PDF in `samples/<CASE>/` as the source of truth. Master and House are read from the air waybill by position;
  Invoice, Packing List and Manifest have no fixed layout: key fields are read from the document by label, every other value Nexus shows must appear on the
  document, and an empty field whose value is on the document is a FAIL.
- Verdicts: PASS, FAIL, REVIEW (partly matches, e.g. Nexus adds words to a name: look by eye), INFO (data Nexus holds itself, e.g. Party ID),
  NOT_VERIFIABLE (could not be read from the document).
- The Shipment Details row is checked too: Bill No. = the PDF's AWB number, Branch = destination airport (MAA = Chennai), Job Type = New Job, Status = CW Sync Pending.
- Party addresses are compared with the document (a different place = FAIL, same place with different wording = REVIEW).
- The check looks in Nexus's **Pre-Alerts** tab only. A duplicate in *Others* shows as NOT_RECEIVED.
- Same flow with Claude: say "Execute AIR_SINGLE_HOUSE_DAILY" (uses many more tokens; see `air/AIR_SINGLE_HOUSE_DAILY.md`).

_Last updated 2026-10-26: trace folders, root cause, baseline, bug history, case documentation, default mapping._

## Run report (today's run only)
`./nx runreport [--date yyyy-mm-dd]` prints observations per case, the bugs found in the run, raised bugs still there, and previously raised bugs that passed in this run. `run_regression.sh` prints it automatically at the end of every run (not on `--dry-run`) and saves `runs/_reports/runreport_<date>_<time>.md`.

## Live view of a run
No browser tab opens during a run any more. The live status page is still written (**runs/_live/index.html**, same text in `runs/_live/live.log`): open it yourself if you want to follow a run. Turn it off with `NEXUS_NO_LIVE=1`.

## Automated test report (one browser launch per run)
`./nx runreport [--date yyyy-mm-dd]` writes **runs/_reports/runreport_<date>.html** and opens it ONCE; `run_regression.sh` does this at the end of every run. Individual `validate*` / `suite` commands only write the file (path printed), they no longer open tabs. The page has the Nexus logo and the heading "Automated test report" and **consolidates every run of the day**: summary tiles, a timeline of all runs of the day (sends, mapping checks, Master / House / Manifest / Invoice / Packing List checks), the latest result per case, and per case: all attempts of the day, mapping, what Nexus holds, root causes, the fields that did not match, every field checked (collapsible per document), screenshots and the bug sections. Nothing is added to the bug sheet from it. `NEXUS_NO_LIVE=1` stops it opening.

## Sea single house (send, then validate one case at a time)
- Cases: `SEA-REG-001` to `SEA-REG-009` (009 = DAP-FJ-0002952: House Incoterm must show DAP) in `knowledge_base/testcases/Sea_Single_House_Daily_Regression.xlsx`; samples in `samples/SEA-REG-00x/`.
- Preview, nothing sent: `./run_regression.sh sea-daily --dry-run --no-wait` (one case: `./run_regression.sh SEA-REG-002 --dry-run`).
- Send (only on request, after the old pre-alerts are deleted): `./run_regression.sh SEA-REG-002`. The subject is `SEA-REG-002 | QA agent trigger ... | Pre-Alert FJ-0001497 | CONSOLIDATED (MASTER+HOUSE)`.
- `--validate` in the suite is still refused for Sea; run the checks after sending, one case at a time: `./nx validate --cases SEA-REG-001`, then `validate-master`, `validate-house`, `validate-docs` with the same `--cases`.
- Sea data checks (`nexus_agent/sea_check.py`): every Nexus field is looked up in the text of its own bill (MBL pages for the Master, HBL pages for the House); PASS = printed on the document, FAIL = not printed, REVIEW = partly, or a scan read with OCR. Invoice / Packing List use the usual docs check on the Sea parts.
- Screening reads Sea bills with `pdf_split_sea` (config): the carrier form is the MASTER, a bill starting with the forwarder reference is the HOUSE; scanned pages are read with OCR (about 2 minutes for SEA-REG-005).
- Source bill: the Sea check uses the bill that prints the bill number Nexus shows (not the first screened bill), so a sample with two bills (SEA-REG-006) is compared page by page against the right one. Dates are read as `21/07/2026`, `Jul.21,2026`, `21 JUL 2026`, `dd/mm/yy` and others.
- Same shipment already in Nexus: a resent or repeated shipment can be absorbed into the existing pre-alert (SEA-REG-005: IPA/2332 grew from 15 to 30 pages; SEA-REG-006 first send created nothing). Delete the older pre-alert (you do it, the agent never deletes) before sending; if no new pre-alert appears after 7 minutes, look for it in the old one.
- Resend after the pre-alert was deleted: `./nx suite --cases SEA-REG-005 --resend --force` (`run_regression.sh` has no `--resend`).
- Expectations changed by the user: SEA-REG-006 maps the Debit Note to the Master (Master + House + Debit Note).
- Results are recorded in the Sea workbook (columns Last Known Nexus Job, Daily Result, Nexus Job (today), Tester / Remarks), today's run report (`./nx runreport`), the bug sheet (on your yes, with the screenshots and the pre-alert PDFs) and `docs/PROGRESS_LOG.md`.
- Findings you confirmed as not a bug (party-master names/addresses/postal codes, carrier name, Pol/Pod codes, freight payment, FCL/LCL, volume and unit reviews) are marked NOT_A_BUG and shown as KNOWN in later runs.

## Evidence in Google Drive
`./nx upload-evidence [--date yyyy-mm-dd]` (also run by `run_regression.sh` at the end of every run) puts the day's evidence in `Regression testing / Nexus Automated Test Evidence / <yyyy-mm-dd> /`: `01 Test runs/<CASE> - <IPA>/` (screenshots), `02 Bugs/` (evidence of bugs logged that day) and `03 Report/` (the Automated test report as PDF). Bugs are therefore separated by date. Earlier bug evidence stays in `Reg - Air & Sea / dd-mm-yyyy`.
