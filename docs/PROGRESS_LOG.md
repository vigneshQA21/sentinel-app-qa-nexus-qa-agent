# Progress log (day by day)

Newest status first, then one section per day in order. Add a note any time with `./nx log "what changed"`.
The agent (Claude) also adds an entry whenever we finish a piece of work.

## WHERE WE LEFT OFF  (last updated 2026-10-26, end of day)

**Regression status (air, single house):**
| Case | Mode | Status | Nexus job | Bugs in the sheet |
|---|---|---|---|---|
| REG-001 | Consolidated | Fully validated (mapping + 5 documents, field by field) | IPA/2144 | rows 230-233 |
| REG-002 | Consolidated | Fully validated (+ Debit Note, PO / Shipper Document) | IPA/2185 | rows 234-236 |
| REG-003 | Consolidated | Validated (House number read as a phone number; documents left unmatched; invoice not classified) | IPA/2191 | rows 237, 238 |
| REG-005 | Consolidated | Validated after the sample was de-duplicated (invoice was in the PDF 3 times); differences were party-master / checker artefacts, no bug | IPA/2204 | none |
| REG-006 | Individual | Mapping checked: Master arrived as its own pre-alert (IPA/2210), Manifest linked with the House, not the Master. Data checks not built for several pre-alerts | IPA/2206 + 2210 | rows 240, 241 (High) |
| REG-009 | Consolidated (scan) | Mapping PASS (random document stays Unclassified, as expected); data now validated from the scan with OCR (2026-10-27): Master 41 fields (32 PASS, 9 REVIEW), House 42 (30 / 12), Manifest 8 (7 / 1) | IPA/2218 | none |
| REG-007 | Individual | NOT RUN: shares house ORAE26040499 with REG-003 (IPA/2191 must be deleted first) | - | - |
| REG-011, REG-016 | Individual | NOT RUN: no sample documents | - | - |

**Waiting on:**
- You: delete IPA/2191 (REG-003) in Nexus, then REG-007 can be sent and validated.
- You: decide the pending candidates (REG-002 Invoice Gross Weight is parked as "RECHECK after the packing-list fix"; the old House-missing candidate from the deleted IPA/2124; the REG-001 House shipper items).
- Developers: the 11 bugs logged in the UAT sheet (re-test every day with `./run_regression.sh <CASE> --validate`; every run prints "STILL THERE xN" for raised bugs and "possibly FIXED" when one no longer shows).

**Built on 2026-10-26:** Debit Note / Shipper Document (PO) checks; reader for short "Check B/L" forms; known-issue baseline; `./nx history` (bug repeat tracker); `./nx casedoc` (validations written into the test-case Excel); per-case TRACE folder with `index.html` and PROBABLE ROOT CAUSE lines; Pre-Alerts page, expanded row and Others tab captured on every check; default mapping when the Excel text has no arrows; Unmatched/Unclassified sections are now read.

**Next ideas:**
1. REG-007 (after IPA/2191 is deleted); samples for REG-011 and REG-016.
2. Data checks for individual cases (Master, House, documents that live in several pre-alerts). (OCR for scanned samples: DONE 2026-10-27.)
3. Data-level root cause ("party-master value, not the document"); fix the checker flaws seen today (multi-value PO numbers, volume / destination reads on non-IATA layouts, K = KGS).
4. XML / CargoWise check (Debit Note must not be sent in XML); auto-delete after validation (planned last); HTML run report; nightly run.
5. Housekeeping: the GitHub repo is public. Make it private before it is shared.

**Things to remember every day:**
- The Nexus login lasts only a few days: when a run says "session expired", run `./nx login` (log in, close the window).
- Delete the old pre-alerts of a case in Nexus before re-running it; check first (`./nx validate --cases <CASE> --wait 0` must say NOT_RECEIVED). Nexus can take ~10 minutes to show a new pre-alert, so wait before re-sending.
- Nexus search filters by ID only; the list page renders only the ~25 newest rows.
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

## 2026-10-26

- Check-only run of REG-001 + REG-002 on existing pre-alerts (IPA/2144, IPA/2185), nothing sent. Baseline worked (known issues shown as KNOWN). Glitch: validate-house with two cases could not find the 2nd pre-alert (passed when run alone); to investigate.
- REG-002 Invoice Currency Code was a checker miss (invoice prints US$): fixed, candidate closed. Gross Weight 63 is on the Packing List page 7, not the invoice: consequence of the Packing-List-as-Invoice bug (row 236).
- REG-002 Invoice Gross Weight 63 accepted as not a bug: root cause is the Packing-List-as-Invoice classification bug (row 236). Marked RECHECK: shown as KNOWN with a reminder on every run until the fix; re-verify after it.
- REG-003 sent (1 consolidated email, subject ref ORAE26040499) at 12:24; REG-007 not touched. Screening found MASTER+MANIFEST+INVOICE+HOUSE; the Delivery Note was not detected (pages 5-6 of the sample have no text). Validation after Nexus processes it (3 min buffer).
- REG-003 in Nexus as IPA/2190/2026-27 (~12 min after send): only a House (TEL0635070676: HAWB + Shipper Document); Master, Manifest, Invoice and Delivery Note not found; subject ref was ORAE26040499. 4 mapping candidates pending your decision, nothing added to the bug sheet.
- REG-003 (IPA/2190/2026-27) analysed against the sample (all 5 docs present: Master p1, Manifest p2, Invoice p3, House p4 ORAE26040499, scanned Delivery Note p5-6). Nexus read the House bill number as TEL0635070676 (the shipper phone number) instead of 'HAWB No: ORAE26040499'; Master, Air Manifest and Delivery Note (correctly classified) sit under UNMATCHED documents; Invoice not classified (Missing Docs: Invoice, job progress stuck at 67%); a Shipper Document is linked under the House (probably the invoice page). TODO: make the mapping check read the Unmatched/Unclassified sections so it says 'unmatched' instead of 'not found'. IPA/2073 (REG-007) was still listed in Nexus. Nothing added to the bug sheet.
- Mapping check now opens the Unmatched/Unclassified sections (they were never read: the page shows headings in capitals by CSS, so an exact-text click missed them) and recognises DELIVERYNOTE. REG-003 re-checked: Master, Manifest, Delivery Note under Unmatched. Waiting for the user to delete IPA/2190 before the REG-003 re-send.
- REG-003 evidence screenshot saved (house number TEL0635070676 vs HAWB No ORAE26040499, documents under Unmatched). Candidate kept pending: to be added to the bug sheet only if the issue persists after the re-run (user's instruction).
- REG-003 re-executed (IPA/2191, nothing duplicated: IPA/2190 and 2073 had been deleted). House number still read as TEL0635070676, so the bug was added to the sheet (row 237, Medium, Not Taken; seen in 2 pre-alerts). This time Master, Manifest and Delivery Note were linked correctly; Invoice still missing (Shipper Document under House). Checker issues to review: unit K vs KGS, nature of goods text, Packing List expected-but-absent error.
- REG-003 first attempt (IPA/2190) logged as one bug (sheet row 238, Medium, Not Taken): Master, Manifest and Delivery Note left under Unmatched, Invoice missing, Shipper Document under House. The 2190 mapping candidates are closed as covered by that row.
- REG-003 row 238: evidence replaced with a cropped screenshot of the viewer's left panel (HAWB, Shipper Document linked; MAWB, Air Manifest, Delivery Note under Unmatched; Unclassified empty). The row had shown the full viewer where the house number dominated.
- REG-003 row 238: screenshot chip removed from the File Name cell at the user's request (only the source-PDF chip remains). Screenshot files stay in Drive; nothing deleted.
- Evidence: every check now saves the Pre-Alerts page (prealerts_list.png) and the expanded row (prealert_expanded.png), and archives every screenshot under runs/<date>/<case>/archive/<time>_<IPA>_<name>.png so later runs never overwrite earlier evidence.
- Daily re-test view: already-raised bugs do not fail a case but every run now prints 'STILL THERE xN' for each (N = pre-alerts it was seen in, with the bug-sheet row) and 'possibly FIXED' when a logged bug no longer shows. Fixed: parent dropdown retry, CSV writer ignoring extra keys.
- Run for 4:30 deadline: REG-005 and REG-009 started (send+validate, background) 15:22; REG-006 (6 individual emails) sent 15:28 (old IPA/551 confirmed absent via Nexus ID search). REG-007 held: same house as REG-003 (IPA/2191 still in Nexus). Nexus search box filters by ID only; the list page renders only ~25 recent rows.
- REG-005 re-triggered 15:34 (IPA/2203/2026-27). Mapping PASS (Master, House, Manifest, Invoice, Shipper Document). Default mapping added for cases whose Excel text has no arrows (REG-005/006/007/009). Data checks: Master 7 FAIL, House 5 FAIL + 2 REVIEW, Invoice 2 FAIL (PO/Order no); many look like reader limits on non-IATA layouts (destination 'Bangalore 963/28.08', volume 21.407, KGS), to review by eye. Nothing added to the bug sheet. REG-006/009 (sent 15:26-15:28) are not in Nexus any more (user deleted); REG-007 still blocked by REG-003 IPA/2191.
- REG-005 sample de-duplicated: the invoice EI268002192 was in the PDF three times (text copy p4-5, scans p6-7 and p8-9). Kept the text copy: sample is now 6 pages (Master, Manifest scan, House, Invoice 2 pages, Insurance certificate). Original backed up in samples/_backup_original/REG-005/; Regression Set copy updated. Waiting for the user to delete the existing pre-alert (IPA/2203) before the re-run.
- REG-005 re-run with the de-duplicated sample (IPA/2204/2026-27, appeared 183s after sending): mapping PASS, Invoice pages under House 4 -> 2 and no Unmatched copy. Data checks unchanged: Master 7 FAIL, House 5 FAIL + 2 REVIEW, Invoice 1 FAIL (PO number 'EN15481, EN15455' joined with comma = checker issue), Manifest/Packing List errors (manifest is a scan). Nothing added to the bug sheet.
- REG-006 (6 individual emails, 16:08): Nexus did not keep them in one shipment. Pre-Alerts tab: IPA/2206 (Manifest email, with House, Invoice, Packing List linked) and a SEPARATE pre-alert IPA/2210 (Master email). Others tab holds IPA/2207-2209, 2211 (Invoice, Packing List, Debit Note, House emails as follow-ups). Mapping check on IPA/2206: Master and Debit Note not found. Screenshots of both tabs saved. Nothing added to the bug sheet.
- REG-006: user confirmed two mapping bugs (House not linked to Master although the House carries the master number 160-15585765; Manifest linked with the House instead of the Master). Prepared as pending candidates with the Pre-Alerts tab evidence; waiting for the user's yes to add them to the sheet.
- REG-006: two mapping bugs logged in the bug sheet at the user's request, Priority High, Status Not Taken, with the Pre-Alerts page screenshots: (1) House not linked to Master although it carries the master number 160-15585765 (Master created as separate pre-alert IPA/2210); (2) Manifest linked with the House instead of the Master.
- REG-006 row 241: evidence replaced with the user's screenshot of the IPA/2206 viewer (parent dropdown lists only House (FLD6445) and Air Manifest, no Master).
- REG-006 row 240: evidence replaced with the user's Pre-Alerts page screenshot (IPA/2206 and IPA/2210 as separate pre-alerts, IPA/2210 expanded showing the Master 160-15585765).
- Trace + root cause: every check now writes a numbered trace folder per case/pre-alert (runs/<date>/<case>/trace_<time>_<IPA>/ with index.html) covering the Pre-Alerts page, expanded row, each viewer parent, the Others tab and the data panels; the mapping check prints PROBABLE ROOT CAUSE lines (wrong house number, unmatched docs, Master as own pre-alert, follow-ups in Others, unclassified doc). Fixed: open_list always selects the Pre-Alerts tab; Unmatched counts only documents linked under no parent.
- REG-009 (scanned sample, FJ-0001132) sent 17:15 and validated: IPA/2218/2026-27 appeared 184s after sending. Mapping PASS: Master 932-78831771, House SUSAO008522, Air Manifest (2 pages); the random document stays under Unclassified, as the test case expects. Data checks cannot run: the sample has no readable text (scan), so Master/House/Manifest/Invoice/Packing checks report 'no page found'. Nothing added to the bug sheet. Next: REG-007 after IPA/2191 (REG-003) is deleted.
- End of day 2026-10-26: documentation brought up to date (where we left off, README scope, commands). Manager update prepared for the Zoho ticket.

## 2026-10-27

- Bug sheet read-only analysis (27-Oct): of our 11 rows, 1 Development Completed (230), 1 Discussion needed (231), 4 Not an issue (232-235: party master / '1 Pallet'), 1 In development (236), 2 Code Review (240, 241: dev root cause = MAWB normalisation, missing '-'), 2 Not Taken (237; 238 'not reproducible now, check backend DB'). Rows 234-236 were logged on 24-Oct, not 26-Oct. Manager update redrafted; root-cause hint for 'Master as own pre-alert' corrected to the dev finding.
- OCR for scanned documents implemented (rapidocr-onnxruntime, auto-orientation, disk cache, used only when checking): REG-009 Master/House/Manifest now compared field by field (differences on a scan are REVIEW, never FAIL), REG-005 scanned manifest 8/8 PASS; case-listed documents only (no Invoice/Packing errors for REG-009). 87 tests pass.
- Repo: samples/, knowledge_base/ and runs/ un-ignored by the user's decision (public); secrets/, state/, .env stay ignored. Commit 385fa7b created (735 files); the push needs the user's GitHub login in a terminal.
