# Mistakes made and what changed

Wrong things the agent did, found by the user or by checking, and how each was fixed. Newest first (updated 10-Nov-2026).

## 10-Nov

### 1. Named a blocking job from old data without checking
- **What happened:** I said REG-002 would be blocked by "pradeep.e's job IPA/2525" and called it "not in Nexus" without having looked. The pre-send check found a different job (IPA/2541, same shipment).
- **Cause:** I reused a job number from 06-Nov data and treated it as current.
- **Fix / rule:** name only what a check run now returned and say what is unverified (memory: name-only-verified). The pre-send bill check (`./nx preflight`) is now run before every send.

### 2. Sea checker results were shown as "failures to confirm" before they were checked against the bills
- **What happened:** I listed 17 Sea items (3 to 19) as failures that need the user's confirmation, using the checker's wording ("empty in Nexus, but the bill prints ..."). When the evidence was opened, three groups were not bugs: SEA-REG-003 House "Consignee Address" (item 15), the Master "empty Consignee Name and Address" items (3, 9, 12) and SEA-REG-001 Master Place of Delivery / Final Destination (item 4). I also called item 15 "Consignee Address" and item 4 "looks real" before looking.
- **Cause:** the Sea checker (`sea_check.py`) names a party block by the heading above it in Nexus's field list, so an empty Notify Party address (bill prints `SAME AS CONSIGNEE`, no address) or an empty "For Delivery Details" block (bill has no such party) is reported as an empty Consignee. For item 4 my text extraction joined the ports row into one line (`CMA CGM COLUMBIA GENOA KOLKATA(CALCUTTA)`) and I read KOLKATA as the final place of delivery; the word positions show it under PORT OF DISCHARGE, and the FINAL PLACE OF DELIVERY box is blank.
- **Fix / rule:** each item was checked against Nexus and the bill with a screenshot or crop and shown to the user; item 15 was marked not a bug on the user's word; items 3, 4, 9, 12 await the user's decision. Before an item goes in a "needs your confirmation" list: (a) name the Nexus block by its own heading in the viewer, (b) read the bill column by position (word coordinates or a crop), not from joined text, (c) show the evidence.
- **Still to fix:** `sea_check.py` should name the block by the viewer heading (Consignee / Notify Party / For Delivery Details) and not report an empty address when the bill prints `SAME AS CONSIGNEE`.

### 3. Said REG-009 had the same `K` vs `KGS` pattern and was accepted as not a bug
- **What happened:** when I first raised the REG-007 House weight units I said REG-009 House had the same pattern, accepted on 28-Oct. The stored REG-009 candidates have `KGS` in Nexus and "not found in the scan" as the expected value, reviewed on 29-Oct as scan / OCR limits. The real `K` vs `KGS` candidates were REG-003 (26-Oct) and REG-001 (05-Nov), both still pending.
- **Cause:** I recalled the pattern from memory and did not look the candidates up.
- **Fix / rule:** corrected in the chat before the row was written; row 274 carries only REG-007. Look up the history of a field in the local candidates and the sheet before saying it was seen before.

### 4. Guessed an IPA for a case in a draft
- **What happened:** in the draft for the REG-007 weight units I wrote "REG-003 (IPA/2314-era candidate from 26-Oct)". IPA/2314 belongs to REG-006 (checked later in the candidate list); the REG-003 candidate carries another IPA.
- **Fix / rule:** same as 1: name an IPA only from a check that returned it.

### 5. A launcher shell's "completed" notice read as the run being finished, and a validation chain stopped after step 1
- **What happened:** background commands reported "completed (exit code 0)" while the suite / validation was still running (the launcher shell exits at once). Separately, the four-step Sea validation was chained with `&&`, so the first step (mapping, which returns a failure code when any case fails) stopped the chain: Master, House and document checks never ran until I started them again with `;`.
- **Fix / rule:** a run is finished only when no `nexus_agent` process is left and the log shows its end marker (`CHAIN_DONE` for chained runs). Chain the validation steps with `;`, never `&&`.

### 6. The message said "19 items, numbered 3 to 19 plus the Master mapping"
- **What happened:** items 3 to 19 are 17 items; the Master mapping is item 19, not an extra one. The user caught the number when asking to see them again.
- **Fix / rule:** count a list from the list, not from the numbering text.

## 06-Nov

### 2. Air cases were checked against the Sea job with the same number
- **What happened:** the check found a case's pre-alert with a substring match, so `REG-002 |` also matched `SEA-REG-002 |`. Air REG-002 was compared with the Sea job, giving false "not found" results and 38 false bug candidates. The reference lookup (`ref_for_case`) had the same fault: Air REG-009 took the Sea reference.
- **Fix:** both now require the subject to START with the case id. Tests added. The invalid REG-002 results were discarded and the false candidates were never logged.

### 3. Bug row 264 gave the wrong cause (my own row)
- **What happened:** I wrote that the extra Sea pages in Air job IPA/2504 came from SEA-REG-005 (IPA/2535) and added a wrong REG-002 note. The Others tab (Related Email column) showed they came from SEA-REG-003 and SEA-REG-007 (6 + 3 + 3 = 12 pages).
- **Cause:** I assumed the cause from timing and did not read the Related Email column first.
- **Fix:** row 264 corrected (description and chips: the SEA-REG-005 PDF replaced by the SEA-REG-003 and SEA-REG-007 PDFs). Rule: read the link in Nexus before writing a cause.

### 4. A chip disappeared from row 247 and I said it was there
- **What happened:** I checked the file name text, not the chip, and told the user the chip existed. Colleagues edit the sheet at the same time and the chip was gone.
- **Fix / rule:** after any write that adds chips, re-read `chipRuns` about a minute later, compare the count, re-add a missing chip and report the count (skill rule 8; built into `attach_evidence`).

### 5. Resend and checks ran while the internet was down
- **What happened:** the send step failed on a DNS error and the checks that followed ran on cases that were never sent. The results meant nothing.
- **Fix:** the chain was stopped and discarded; the cases were resent once the connection was back. Failed sends are now listed as not sent, not as checked.

### 6. Delete command: several wrong results on 05-Nov and 06-Nov
- The sender check could not read the "From" column, so it deleted nothing and printed "ready to send again" while the rows were still in Nexus. A bill filter left on in one tab made later list loads hang for 60 seconds and report "nothing to delete". A killed run left a staged sample copy that blocked the next send. All fixed in `cleanup.py`; "ready to send again" is printed only when nothing is left.

### 7. The Cliq draft listed rows 262 and 263 as raised on 06-Nov
- They were raised on 04-Nov and 05-Nov. I had not looked at the Date Reported column. Corrected draft sent to the user.

### 8. Stopped a run with a process pattern that killed my own shell (twice)
- `pkill`/`pgrep -f` matched the command that contained the pattern. Now I stop runs by process id.

## 02-Nov to 04-Nov

### 9. Sea checker false findings
- The House check read the wrong page for samples with two bills (16 false FAILs on SEA-REG-006), a date written `Jul.21,2026` was not recognised, and empty Nexus fields were shown as INFO and hid real gaps. Fixed by choosing the bill by its number, new date forms and an empty-field rule.

### 10. Evidence and wording
- Bug row 252 was first logged against the wrong job (IPA/2386) and was corrected to IPA/2391.
- Generic full-page screenshots were not accepted as bug evidence; each bug now carries the failing field next to the matching bill block.
- A "Voyage Number blank" finding on House B was my error (the bill prints no voyage number) and was retracted.

## 29-Oct


### 1. Bug row 247 (REG-009 House Shipper Postal Code) had the wrong "Expected" value
- **What happened:** the row said `Expected : 9442, 0065, 0000`. The document prints `28451` ("LELAND NC 28451 US").
- **Cause:** on a scanned page the words are glued together (`LELANDNC28451US`), and the reader looked only for a number standing alone. It then listed unrelated 4-digit numbers (phone number end `9442`, agent code `0065`, `0000`) as the "printed" codes.
- **Why it was missed:** the bug was logged straight from the candidate list, without checking the Expected text against the document.
- **Fix:** sheet cell E247 corrected (only that cell). New `printed_codes()` in house_check.py takes the code after a two-letter state first, and only the first one. Test added.

### 2. Bug row 246 (REG-009 House Shipper Address) quoted raw OCR text as "Expected"
- **What happened:** Expected showed `CYGNUSTECHNOLOGIES Air Waybill Shipco Transport Inc. 1523OLDEWATERFORDWAY 4849Massachusett ...`, the start of the whole page text, not the shipper address.
- **Fix:** sheet cell E246 corrected (only that cell): Expected `1523 Olde Waterford Way, Leland NC 28451 US`, Nexus value kept exactly as shown.
- **Not changed:** the Status, Comments and Priority of row 246 were set by someone else in the sheet. Left alone.

### 3. Rows 246 and 247 were logged with a default Priority
- Row 247 got Priority High, the default, although no priority was chosen. The same default caused two wrong priorities before (see CHALLENGES.md, section 11).
- **Rule from now on:** ask for the priority of every bug before logging it, never rely on the default.

### 4. Earlier local "not a bug" mark on the two REG-009 House items
- I marked 34 REG-009 candidates as not a bug after "these are not bugs". The user then named these two as bugs. They were reversed for those two only.
- **Rule from now on:** when the user accepts a group of items, mark only the ones named, and list them back before marking.

## Checks to do before any row goes to the sheet
1. Read the document value for the field myself and compare it with "Expected".
2. Never use a list of OCR numbers or the raw page text as "Expected".
3. Ask for the Priority.
4. After writing, read the row back and compare every cell.
5. Change only the cell that is wrong; never touch Status, Comments or other people's edits.
6. After writing chips, re-read the chip count a minute later and report it.
7. Name a job, row or status only when a check run now returned it.
8. Match a case by the start of its subject (`REG-002 |` is not `SEA-REG-002 |`).
9. Before writing a cause into a bug, read the link or value in Nexus itself.
10. Before a checker failure goes in a "needs your confirmation" list, name the Nexus block by its viewer heading and read the bill by column position (crop), with the evidence image.
11. A background task's "completed" is not the end of the run: check that no `nexus_agent` process is left and the log's end marker is there.
