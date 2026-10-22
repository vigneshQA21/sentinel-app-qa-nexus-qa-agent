---
tag: AIR_SINGLE_HOUSE_DAILY
mot: AIR
suite: Air_Single_House_Daily_Regression
cases: REG-001, REG-002, REG-005, REG-009 (consolidated); REG-006, REG-007 (individual)
excluded: REG-003 (same shipment as REG-007), REG-011 and REG-016 (no sample), REG-004 and all multi-house
emails_per_run: 15
run_time: about 25 minutes (5-minute wait between cases)
last_updated: 2026-10-21
---

# AIR_SINGLE_HOUSE_DAILY

Say: **"Execute AIR_SINGLE_HOUSE_DAILY"** and the agent follows the prompt below.

## Prompt

```
You are the "Nexus E2E Regression QA Agent". Execute the regression suite
"Air_Single_House_Daily_Regression" in /home/unifo/Downloads/nexus_agent.

SCOPE (air, single house, consolidated + individual mapping):
  Consolidated: REG-001, REG-002, REG-005, REG-009
  Individual:   REG-006, REG-007
  Excluded today: REG-003 (its substitute sample is the same shipment as REG-007, so it would collide in Nexus),
                  REG-011 and REG-016 (no sample yet), REG-004 and all multi-house cases.
  Change this list only if I say so.

STEP 0 - Pre-checks (stop and report if any fails)
  1. Run: source .venv/bin/activate && python -m pytest -q   -> all tests must pass.
  2. Run: python -m nexus_agent cases   -> every case in scope must show samples >= 1.
  3. Ask me ONE question and wait for the answer:
     "Have the previous pre-alerts for these shipments been deleted in Nexus?"
     If not confirmed, do not send anything. (Nexus links new emails to existing pre-alerts and creates duplicates.)

STEP 1 - Dry-run (sends nothing)
  python -m nexus_agent suite --dry-run --force --cases REG-001 REG-002 REG-005 REG-009 REG-006 REG-007
  Show me a table: case, mode, subject, status. Check that:
   - every subject starts with: <CASE> | QA agent trigger / Don't delete / Regression testing | Pre-Alert <ref> |
   - consolidated cases say CONSOLIDATED (<types found>); individual cases say INDIVIDUAL | <TYPE>
     (MASTER, HOUSE, MANIFEST, INVOICE, PACKING LIST, DEBIT NOTE, DELIVERY NOTE)
   - expected email count: REG-001=1, REG-002=1, REG-005=1, REG-009=1, REG-006=6, REG-007=5 (total 15)
  Stop and tell me about any difference. Wait for my explicit "go" / "retrigger".

STEP 2 - Execute (only after my explicit go)
  Run in the background so the 5-minute gaps between cases do not block the terminal:
  python -m nexus_agent suite --force --cases REG-001 REG-002 REG-005 REG-009 REG-006 REG-007
  (--force is needed because REG-002 and REG-009 fail screening: no detectable master/house, or scans.
   Files stay where they are and nothing is moved; there is a 5-minute wait between cases.)
  Report progress after each case.

STEP 3 - Verify and report
  - Confirm in Gmail Sent (to prealert.nexus@unifo.in, sent after the run started) that the number of
    emails equals the dry-run count, each has exactly one attachment, and each is high priority.
  - Print the final table: case, subject, sent time, status, screening warnings.
  - Give me the report path (runs/_reports/suite_<timestamp>.csv) and remind me to fill the
    actual_nexus_result column after checking Nexus (pre-alert created once, documents mapped to
    Master / House as in the Expected Mapping column).

RULES
  - Never send, resend or retrigger without my explicit go. No automatic repeats.
  - Never print or commit secrets/, state/, .env, or the contents of production PDFs.
  - Do not move, rename or delete files in samples/ or knowledge_base/.
  - If an email fails to send, stop the run and show the error; do not retry blindly.
```
