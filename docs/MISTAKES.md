# Mistakes made and what changed

Wrong things the agent did, found by the user or by checking, and how each was fixed. Newest first.

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
