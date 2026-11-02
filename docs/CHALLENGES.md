# Challenges in the project

What made the Nexus regression hard, what we did about it, and what is still open. Dates are from [PROGRESS_LOG.md](PROGRESS_LOG.md).

## Summary

| # | Challenge | Type | Status |
| --- | --- | --- | --- |
| 1 | Nexus groups the same emails differently on every run | Nexus behaviour | Open (bug row 245 re-tested Fixed on one run) |
| 2 | Old pre-alerts turn new emails into duplicates | Nexus behaviour | Managed by a manual delete step |
| 3 | Nexus is slow and uneven to show a new pre-alert | Nexus behaviour | Handled by timed polling |
| 4 | Scanned samples have no text | Documents | Handled with OCR (results marked REVIEW) |
| 5 | Samples do not match their test case | Documents | Fixed case by case |
| 6 | Documents are laid out differently, so the reader can misread | Documents | Partly handled, ongoing |
| 7 | Nexus screens are hard to automate | UI | Handled, fragile to UI changes |
| 8 | Nexus login expires and cannot be automated | Access | Manual login every few days |
| 9 | A bug can look different from run to run | Triage | Handled with a baseline and bug history |
| 10 | Edited pre-alerts give differences that are not bugs | Triage | Rule: re-run on a fresh pre-alert |
| 11 | Google Sheets, Drive and Gmail integration | Integration | Fixed, a timeout fix added 29-Oct |
| 12 | Cost of a wrong send or a wrong bug entry | Process | Controlled by rules |
| 13 | Public repository | Process | Decision recorded, secrets stay out |
| 14 | Coverage gaps | Scope | Open |

## 1. Nexus groups the same emails differently on every run
The same five REG-007 emails produced five different results on 27-Oct (IPA/2228, 2231, 2240, 2248, 2250):
- the Delivery Note was sometimes unmatched and sometimes in the House;
- the Master was sometimes its own pre-alert;
- the Invoice was classified as a Shipper Document in 4 of 5 runs.

REG-003 and REG-006 showed the same pattern. The cause is not known. One hypothesis is that emails sent seconds apart race each other.

**Effect:** one run cannot prove a bug is fixed or still there. A single pass does not mean the problem is gone, because the result can change on the next run.

**What we did:** merged the related findings into one bug (row 245), kept every run's evidence, and re-tested after the dev fix. The re-test on IPA/2250 was Fixed. The root-cause hints in each trace record what happened.

**Still open:** test sending the individual emails with a gap between them.

## 2. Old pre-alerts turn new emails into duplicates
Nexus links a new email to an existing pre-alert with the same reference, so repeats land in the *Others* tab. The agent cannot delete in Nexus (by decision), so a person deletes the old pre-alerts before every re-run. A shared house number makes it worse: REG-003 and REG-007 use the same house (ORAE26040499), so REG-007 had to wait until REG-003's pre-alert was deleted. REG-003 is now excluded for that reason.

## 3. Nexus is slow and uneven to show a new pre-alert
A pre-alert appears about 3 minutes after sending (183 s on several runs), but a REG-003 pre-alert took about 12 minutes. The Nexus search filters by ID only, and the list page renders only the ~25 newest rows. A check made too early shows an incomplete result.

**What we did:** a timed check (first look at 3 min, poll every 20 s up to 7 min, then NOT_RECEIVED).

## 4. Scanned samples have no text
27 of 72 air samples are scans. Nothing can be read from them directly (REG-009 and the REG-005 manifest).

**What we did:** OCR (added 27-Oct, with automatic rotation and a cache). A difference found on a scan is REVIEW, never FAIL, because OCR can misread characters (for example I and l in flight numbers).

## 5. Samples do not match their test case
- The REG-002 sample had no House waybill, which produced two false bug candidates caused by the sample.
- The REG-005 invoice was in the PDF three times (text copy plus two scans), so Nexus showed it under House and Unmatched. The sample was de-duplicated, with a backup kept.
- REG-016 is a hypothetical case: no sample can be found, so it is marked not executable. REG-011 had no sample either; one was built from the knowledge-base candidate FJ-0001012 (split into Master, Manifest, House) plus a dummy unclassified document (29-Oct).
- The REG-003 Delivery Note pages have no text, so screening missed it.

## 6. Documents are laid out differently, so the reader can misread
Free-form documents (invoice, packing list) and non-IATA layouts caused checker misses, not product bugs:
- the invoice prints US$, so the currency check failed;
- a PO number joined with a comma failed the match;
- unit K versus KGS;
- the volume and destination read on some layouts;
- Gross Weight was on the Packing List page, not the invoice.

**What we did:** fix each reader flaw as it appears (see "Next ideas" in the progress log). The document stays the source of truth and nothing is hard-coded per sample.

## 7. Nexus screens are hard to automate
- The Unmatched and Unclassified sections were never read, because the page shows headings in capitals by CSS and an exact-text click missed them (fixed 26-Oct).
- The parent dropdown needed a retry.
- A selector can break when the UI changes.

**What we did:** retries, a read of every parent and linked document, and a numbered screenshot trace with an index.html per case.

## 8. Nexus login expires and cannot be automated
The session lasts only a few days (it expired on 24-Oct). No password is stored; the login is done by hand with `./nx login` and only the browser session is saved. The browser stays visible during checks.

## 9. A bug can look different from run to run
The same issue can show up in several pre-alerts, and a fixed issue can silently reappear.

**What we did:** a known-issue baseline (logged bugs show as KNOWN and do not fail the case, only new differences do), a bug history table with `./nx history`, "STILL THERE xN" and "possibly FIXED" on every run.

## 10. Edited pre-alerts give differences that are not bugs
If someone edits the pre-alert in Nexus after it was created, the checks report differences that are not product bugs. Party-master values (names, addresses, "1 Pallet") also turned out to be master data rather than the document: four of our bugs (rows 232-235) were closed as Not an issue.

**What we did:** re-run on a fresh pre-alert, and work on root cause at the data level ("party-master value, not the document").

## 11. Google Sheets, Drive and Gmail integration
- The Sheets and Drive APIs had to be enabled and authorised once.
- Two bug rows were written with Priority High instead of Medium. Only those two Priority cells were corrected.
- **29-Oct:** a Gmail write timeout during a send crashed the whole run after the first email. Only REG-001 had been sent; the other five cases were not.

**Fix (29-Oct):** a longer HTTP timeout, a retry that first checks the Sent folder so a timed-out send cannot create a duplicate, and a failed email is now reported as SEND_FAILED without stopping the other cases.

## 12. Cost of a wrong send or a wrong bug entry
A resend creates duplicates in Nexus, and a wrong row in the shared bug sheet confuses the dev team.

**Rules we agreed:**
- send only on "retrigger" or "go", and ask whether the old pre-alerts were deleted;
- never add a bug without a yes for that specific bug;
- never touch earlier bugs or their status;
- no auto-delete until the full validation is finished.

## 13. Public repository
The GitHub repository is public by decision (samples, knowledge base and run evidence are in it). Secrets, state and `.env` stay out. The progress log recommends making the repository private before it is shared.

## 14. Coverage gaps
- Sea cases are not automated.
- Multi-house cases and REG-004 are out of scope.
- Data checks for individual cases (documents spread over several pre-alerts) are not built yet.
- The XML / CargoWise check (Debit Note must not be sent in XML) is not built.
- There is no auto-delete, HTML run report or nightly run yet.

## Open items
- Developers: bug rows still open in the UAT sheet.
- The REG-002 Packing List is still missing (row 236).
- Pending bug candidates are waiting for a decision.
- The grouping behaviour in challenge 1 is not understood.
