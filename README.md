# Nexus E2E Regression QA Agent

An end-to-end regression suite for **Nexus pre-alerts**. It sends real test documents by email the way a customer would, waits
for Nexus to process them, then checks in the Nexus UI that every document landed in the right place **and that every value Nexus
extracted matches the source document**. Failures become bug candidates; after your confirmation they are logged in the Google UAT
bug sheet with the evidence attached as Drive links.

> **Where are we / what did we do yesterday?** Read [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md) (day by day, with "where we left off" at the top).
> **How do I run it?** Read [regression_prompts/EXECUTE_CMD.md](regression_prompts/EXECUTE_CMD.md).

## The 30-second explanation
1. **Send**: test documents from Quadance go to `prealert.nexus@unifo.in` (one email for a consolidated PDF, one per file for individual documents), high priority, with a subject that names the test case.
2. **Wait and poll**: 3 minutes buffer, then check every 20 s for up to 7 minutes. The time Nexus takes is recorded.
3. **Check the mapping**: Master, House, Manifest, Invoice and Packing List must sit under the right parents.
4. **Check the data**: every field Nexus shows for Master (55), House (60), Manifest (8), Invoice (19) and Packing List (16) is compared with the PDF. The document is the source of truth, so nothing is hard-coded and any sample works.
5. **Report bugs**: each FAIL/REVIEW becomes a candidate with a two-line description and a screenshot. You say yes or no; only a yes writes to the sheet.

What makes it different: the expected values come **from the document you sent** (not from fixed test data), it covers email-to-UI end to end,
it measures how long Nexus takes, and bug logging is human-confirmed, remembers "not a bug" and never duplicates.

```
Quadance PDF -> samples/<CASE>/ -> Gmail send -> (3 min buffer, poll) -> Nexus UI
   -> mapping check -> field checks vs the PDF -> bug candidates -> you confirm
   -> Google bug sheet row + evidence in Drive (chips)
```

## Verdicts
| Verdict | Meaning |
|---|---|
| PASS | Nexus shows what the document says |
| FAIL | Differs from the document (a bug candidate) |
| REVIEW | Partly matches (for example Nexus adds words to a name); look at it by eye (a bug candidate) |
| INFO | Data Nexus holds itself, such as a Party ID, or an empty field with nothing to compare |
| NOT_VERIFIABLE | The value could not be read from the document |

## Folder map
| Path | What it is |
|---|---|
| `nexus_agent/` | The code (`local_sender`, `validate`, `master_check`, `house_check`, `docs_check`, `bugs`, `awb_extract`, `nexus/uat.py` ...) |
| `config/settings.yaml` | All settings: subject tag, timing, bug sheet, Drive folder. `config/selectors.uat.yaml` = the real Nexus screens |
| `knowledge_base/` | Test cases (Excel) and the sample documents (git-ignored: production data) |
| `samples/<CASE>/` | The documents used for each test case (git-ignored) |
| `runs/` | Reports (`_reports/`), screenshots (`<date>/<case>/`), evidence (`evidence/`) (git-ignored) |
| `state/` | Local database, the saved Nexus session, bug-sheet details (git-ignored) |
| `secrets/` | Google logins (git-ignored) |
| `regression_prompts/` | `EXECUTE_CMD.md` (the commands) and saved prompts by tag |
| `docs/PROGRESS_LOG.md` | Day-by-day log and next steps |
| `run_regression.sh`, `nx` | The two entry points (always use the project's own Python) |

## Setup (one time)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```
1. **Gmail:** Google Cloud project, Gmail API, OAuth client "Desktop app" saved as `secrets/gmail_credentials.json`; the first send asks you to authorise the sending mailbox.
2. **Nexus login:** `./nx login` (log in by hand, close the window; only the browser session is saved, never a password). Repeat when a run says the session expired (every few days).
3. **Google bug sheet and Drive:** enable the **Google Sheets API** and the **Google Drive API** in the same Cloud project, then run `./nx bugs --check-sheet` once and click Allow. It connects read-only, finds the tab, maps the columns and checks the evidence folder. Set `bugsheet.evidence_folder_id` (the Drive folder id) and `bugsheet.reported_by` in `config/settings.yaml`.

## Daily use
See [regression_prompts/EXECUTE_CMD.md](regression_prompts/EXECUTE_CMD.md). The main one:
```bash
./run_regression.sh REG-001 --validate    # send, wait, check everything, print every field
./nx bugs                                 # confirm the findings you want logged
./nx log "what we changed or decided"     # add a note to today's entry in docs/PROGRESS_LOG.md
```

## Baseline, history and test-case documentation
- **Known-issue baseline:** findings already logged (or accepted as not a bug) show as KNOWN and do not fail a case; only new differences do.
- **Bug history** (`./nx history`): how many different bugs the regression found, how many times each came back (one count per Nexus pre-alert), status and bug-sheet row.
- **Test-case documentation** (`./nx casedoc`): every validation of REG-001 and REG-002 is written into a new tab of the test-case workbook.

## Rules the tool follows
- It sends only when you run it; before sending it checks the Nexus login, so an expired session sends nothing.
- It never deletes anything in Nexus (the test pre-alerts are deleted by hand until the full validation is complete).
- It never adds a bug to the sheet without your yes for that bug, and never changes an existing row.
- Evidence files are uploaded into the dated folder under `UAT Bugs > Regression testing > Reg - Air & Sea`, and nothing is overwritten or deleted.

## Current scope and status
- **Complete for REG-001** (air, consolidated, single house): mapping plus five document data checks plus the bug flow.
- Other cases with samples: REG-002, 005, 009 (consolidated), REG-006, 007 (individual; sending works, the UI checks for several emails per shipment are not built yet).
- Not done yet: auto-delete after validation, sea shipments, CargoWise/XML check, HTML run report. See the next ideas in [docs/PROGRESS_LOG.md](docs/PROGRESS_LOG.md).

## Tests
```bash
.venv/bin/python -m pytest -q       # 85 tests, including a Playwright run against the bundled mock Nexus
```
`mock_nexus/app.py` is a small stand-in for Nexus used by the tests.

## The earlier flow (still in the code, not used for the regression suite)
The project started as a Gmail-to-Nexus-to-TMS agent (`python -m nexus_agent run`): forward pre-alerts from the inbox, fix shipper data, push the XML
to the TMS and reconcile it. It is kept for reference; its settings are in `config/rules.yaml` and `config/xml_mapping.yaml`.
