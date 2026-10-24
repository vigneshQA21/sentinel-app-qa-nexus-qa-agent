# Progress log (day by day)

Newest status first, then one section per day in order. Add a note any time with `./nx log "what changed"`.
The agent (Claude) also adds an entry whenever we finish a piece of work.

## WHERE WE LEFT OFF  (last updated 2026-10-24)

**Done and working for REG-001 (air, consolidated, single house):**
send the test pre-alert -> wait for Nexus -> check the 5 documents are mapped to the right place -> compare every field Nexus
extracted (Master 55, House 60, Manifest 8, Invoice 19, Packing List 16) with the source PDF -> turn FAIL/REVIEW into bug
candidates -> you confirm each -> bug row in the Google UAT sheet with the evidence as Drive chips.

**Waiting on:** PO decision on the consignee party-master data (name, address, postal code). Logged with status
*Discussion needed* in the bug sheet.

**Next ideas (in the order we talked about):**
1. Run the same full flow on the other consolidated cases (REG-002, REG-005, REG-009), then the individual cases (REG-006, REG-007: several emails per shipment need a different lookup).
2. Auto-delete the test pre-alert after validation (planned last; you delete by hand today).
3. Make it stand out: one-page HTML run report with annotated evidence, "known issue" baseline so only NEW problems turn a run red, write results back to the test-suite sheet, nightly run with a summary.
4. Optional AI assist (bug triage and drafting). PASS/FAIL stays rule-based.
5. Sea shipments; samples still missing for REG-003, REG-011, REG-016; scanned PDFs cannot be read (no OCR).
6. CargoWise / XML push check (in the very first plan).
7. Housekeeping: the GitHub repo is public. Make it private (the config and docs contain internal addresses and real-looking test values) before it is shared.

**Things to remember every day:**
- The Nexus login lasts only a few days: when a run says "session expired", run `./nx login` (log in, close the window).
- Delete the old pre-alerts of a case in Nexus before re-running it (otherwise the new email goes to *Others* as a duplicate).
- If someone edits the pre-alert in Nexus after it was created, the checks can report differences that are not product bugs.

## Working rules we agreed (so nobody has to repeat them)
- Nothing is sent unless you run it or say "retrigger".
- Nothing is added to the bug sheet unless you confirm that bug. Earlier raised bugs are never touched.
- No automatic deletion in Nexus until the full validation is finished.
- The document (PDF) is the source of truth; expected values are never hard-coded.
- No passwords are stored: Nexus login is by hand, only the browser session is saved. Secrets, state and production documents are git-ignored.
- The browser is always visible (headed) during checks.

## 2026-10-15  (day 1: sending the pre-alerts)
- Reviewed the earlier project and agreed the new scope: pre-alert documents come from Quadance (downloaded by hand), are emailed to `prealert.nexus@unifo.in`, and Nexus is checked afterwards.
- Gmail API set up (Google Cloud project, OAuth client, mailbox authorised). Tokens live in `secrets/` (git-ignored).
- Built the Knowledge Base flow: `knowledge_base/consolidated` and `individual`; each PDF is screened (reads the pages: master, house, manifest, invoice, packing list) and sent through Gmail.
- Decisions: a consolidated PDF is sent as ONE email, unsplit (we tried splitting first); individual files go one email each. The HAWB is read from the PDF (the FJ number is the fallback).
- Subject carries a tag so Nexus testers recognise it: `QA agent trigger / Don't delete / Regression testing | ...`, plus the document types found. Emails are sent high priority.
- Named the project "Nexus E2E Regression QA Agent". First real email (FJ-0002136) verified in Gmail Sent.
- Finding: 27 of 72 air sample PDFs are scans (no text), so they cannot be read automatically.

## 2026-10-16  (day 2: test cases and the first regression sends)
- Test cases come from the Excel test suite (`knowledge_base/testcases`). Scope: air, single house, consolidated and individual mapping.
- Built the suite runner: `samples/` library per case, `ingest`, `cases`, `suite`, send report CSV, case ID in the subject.
- Mapped the downloaded samples to the cases: REG-001, REG-006, REG-007 complete; gaps for REG-002/003/005/009/011/016.
- Sent REG-001, 006 and 007 (12 emails). Learned that Nexus links a new email to an existing pre-alert with the same reference, so repeats become duplicates in the *Others* tab. Rule: delete the old pre-alerts first; retrigger only when asked.
- Fixed document type naming (manifest vs house, packing list vs invoice, delivery note).

## 2026-10-21  (day 3: the UI validation starts)
- Organised the air samples in `Regression Set - Air Single House` (one folder per case, with an index). Saved the daily prompt tag `AIR_SINGLE_HOUSE_DAILY`, `run_regression.sh` and the `./nx` wrapper.
- Nexus login by hand (`./nx login`), session saved, no password stored.
- Explored the real Nexus screens (view-only): the email list, the expanded row (Shipment Details), the viewer with its parents (Master, House, Air Manifest) and linked documents.
- Built the timed check: wait 3 minutes after sending, then poll every 20 s up to 7 minutes. REG-001 appeared 183 s after sending.
- Mapping check passes for REG-001: Master, House, Manifest, Invoice and Packing List sit under the right parents.
- Master data check: the Master air waybill is read from the PDF by position and compared with every field in the Nexus Master panel, plus the Shipment Details row (Bill No., Branch MAA = Chennai, Job Type New Job, Status CW Sync Pending). Result: all compared fields pass.
- Rules saved: no auto-delete yet; bugs only with your confirmation.

## 2026-10-22  (day 4: House, Manifest, Invoice, Packing List and the bug workflow)
- Case ID now comes first in the subject (`REG-001 | QA agent trigger ...`); Nexus rows are found by `REG-001 |`.
- Added the House (60 fields), Manifest (8), Invoice (19) and Packing List (16) checks. New verdict REVIEW = partly matches, look by eye.
- Free-form documents (invoice, packing list) are checked by reading key fields by label, and every other value must appear on the document.
- First findings on REG-001: Packing List Date shows the document number glued in front; House consignee postal code differs from the document.
- Bug workflow: every FAIL/REVIEW becomes a bug candidate; `./nx bugs` asks y / n / skip per bug; "not a bug" is remembered; nothing is logged without a yes.
- Git repository created and first commit made.

## 2026-10-24  (day 5: Google Sheets and Drive)
- The Nexus session had expired after 3 days: `./nx login` fixed it.
- Google integration: Sheets API and Drive API enabled in the Cloud project; one Google login covers both (`secrets/google_bugs_token.json`). `./nx bugs --check-sheet` connects read-only, finds the tab, reads the header and maps the columns.
- Learned how the team writes bugs in the **UAT Functionality Bugs** sheet and copied it: next Sl.no, Nexus job, MOT, File Name as chips (evidence + `Doc:` source PDF), Priority, Date dd/mm/yyyy, Reported By, QA Team, Status. New rows go at the end; existing rows are never changed.
- Evidence is uploaded to Drive: `UAT Bugs > Regression testing > Reg - Air & Sea > <dd-mm-yyyy>` and linked as chips, like the team does.
- Logged for REG-001 (IPA/2144/2026-27): Packing List date and House consignee postal code (Medium); consignee name and consignee address (Medium, status *Discussion needed* for the PO).
- Party addresses are now compared with the document (different place = FAIL, same place with different wording = REVIEW); before they were only listed.
- A mistake caught and fixed the same day: the first two rows were written with Priority High instead of Medium; only those two Priority cells were corrected.
- Documentation: this log, README rewritten, commands file updated, `./nx log`.
- Docs: README rewritten, commands file updated for Google Sheets/Drive and the bug flow, ./nx log added; 80 tests pass
- REG-002 studied (read-only) on the existing pre-alert IPA/2124: Nexus has the Master (160-15776084) with MAWB + Debit Note, and the Air Manifest, but no House and no invoice/packing list, because the sample PDF has no House waybill. Two auto-created bug candidates (House missing, Packing List missing) are caused by the sample, not Nexus. Waiting for a sample that contains a House.
- REG-002: generic reader for short 'Check B/L' master/house forms, ISO dates, Debit Note and Shipper Document (PO) checks added; re-checked IPA/2185 read-only. Findings await your decision, nothing logged to the bug sheet.
- REG-002 decisions: logged 3 bugs (rows 234-236): House consignee address and House pieces '1PALLET' (Medium, Discussion needed), Packing List shown as Invoice (Medium, Not Taken). PO as Shipper Document = expected (no bug); Shipper Document shipper name = not a bug. Next: REG-003.
- Baseline + test-case documentation: logged bugs and 'not a bug' items are now KNOWN (visible, they do not fail a case; only NEW differences fail; a bug whose field now matches is reported as possibly FIXED). New command ./nx casedoc writes every validation of REG-001/REG-002 into a new tab of Air_Single_House_Daily_Regression.xlsx (backup first).
- Internal bug history added: table bug_history (one occurrence per finding per Nexus pre-alert), ./nx history shows bugs found, repeats and status. 85 tests pass.
