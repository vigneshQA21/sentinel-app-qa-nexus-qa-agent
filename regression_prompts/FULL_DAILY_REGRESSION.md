# FULL_DAILY_REGRESSION

Say "Execute FULL_DAILY_REGRESSION" and follow this prompt step by step, in order, without skipping a step.
Standing rules still apply: delete only the agent's own tagged pre-alerts, send emails one by one with a gap, run headed,
never log a bug / update a tracker / post to Cliq or Sprints without approval (see the memory rules). Evidence IS uploaded to Google Drive automatically after every run (standing rule, 25 Nov 2026).

---

Run today's full Nexus pre-alert regression and give me a detailed report. Work in this order, and don't skip a step.

1. CLEAN UP
- Find and delete all existing pre-alerts in Nexus left over from earlier runs (Air, Sea, Master, House, Direct BL and multi-house).
- Confirm the deletion by listing what remains. Show me the list before you continue.

2. PREFLIGHT AND DRY-RUN
- Run preflight and a dry-run of every regression case (REG-xxx, AIR_SINGLE_HOUSE_DAILY, SEA-REG-xxx, etc.).
- Show me the case list and wait for my go before you send any emails.

3. EXECUTE ALL REGRESSION CASES
- Send every regression test case to Nexus and wait for each one to process.
- Record the status of each case: processed, failed, stuck or partial.

4. VALIDATE EACH CASE
- Check that each document is mapped correctly: Master, House, Manifest, Invoice, Packing List and Debit Note.
- Check every field against the source PDF (field-by-field data validation).
- For each failure, record the case ID, document, field, expected value, actual value and evidence (screenshot or trace).

5. COMPARE WITH PREVIOUS RUNS
- Compare today's results with the previous run(s), case by case and field by field.
- Classify each difference as:
  - NEW BUG: passed before, fails now (regression).
  - EXISTING BUG: failed before and still fails.
  - FIXED: failed before, passes now.
  - NEW FAILURE: a case or field with no earlier history.
- Check each NEW BUG against the bug tracker and the bug sheet so duplicates aren't raised again.

6. RE-TEST DEVELOPMENT-COMPLETED BUGS
- Open the bug tracker (Zoho Sprints and the UAT bug sheet) and filter for bugs that:
  - were raised from earlier automation runs, and
  - have the Re-test status column set to "Development Completed".
- For each bug, re-run its original case and validate the exact field or scenario that failed.
- Mark each one:
  - PASS: verified fixed.
  - FAIL: still reproducible. Add evidence and a comment on the bug.
  - BLOCKED: can't be tested, with the reason.
- Show me the proposed Re-test status updates before you change anything in the tracker.

7. BUG CANDIDATES
- List new bugs found in this run, with a title, steps to reproduce, expected vs actual result, severity and evidence.
- Do not log any bug until I confirm which ones are real.

8. DETAILED REPORT
Produce the report with:
- Summary: total cases, passed, failed, blocked, pass %.
- Case-wise results table: case ID, type, status and failed fields.
- Comparison with the previous run: new bugs, existing bugs, fixed, and the change in pass %.
- Re-test results for the Development Completed bugs: ID, title, result and evidence.
- Bug candidates (new) with severity.
- Observations, risks and recommendations.

9. ASK BEFORE THE FINAL STEPS
Don't log bugs, update the tracker, or post the daily update to Zoho Cliq or Sprints until I approve. (Evidence goes to Google Drive automatically after every run: standing rule.)
