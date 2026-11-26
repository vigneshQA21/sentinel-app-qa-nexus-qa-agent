# JAPAN_TENANT_BUG_REGRESSION – prompt

Tag: "Execute JAPAN_TENANT_BUG_REGRESSION"  (also runs inside every Japan regression build)

## Context
- Tenant: `--tenant japan` (Org Code LJP). Same mapping and field rules as India.
- Bug source: Google Sheet "Logisteed - Nexus UAT Testing" (id `1hB7HAfvRMvMVPLBUIv-o5AYIeeMQ550qFGVaL2weiEI`),
  tab **"Japan Tenant Bug List"** (gid 1832194176). Columns: Sl no | Job No. | MOT | Issue/Bug | Reported Date | Attachments | Type |
  Status | Re-test Status | Re-test By | Comments, if any | Assigned To | Reported By.
- Lifecycle (same as the India tab):
  1. QA raises a row (Status blank).
  2. Dev sets **Status = Resolved** (or Fixed / Development Completed) when the fix is done.
  3. QA re-tests every row with Status = Resolved/Fixed/Development Completed **and Re-test Status blank**:
     - fixed  -> Re-test Status `Resolved`, Re-test By, evidence named in Comments;
     - not fixed -> Re-test Status `Not resolved`, evidence + what still fails in Comments; dev moves Status back to `In Development`.
  4. Rows with Status In Development / Discussion Needed / Not an Issue are not re-tested; the matching check still runs and
     is reported as a KNOWN finding (not a new bug).
- Rows tested by the agent are reported with Re-test By = the user (Vigneshwaran S) only after the user's yes.

## Step 1 – Log today's confirmed bug (user said yes on 26-11-2026)
Append ONE row to "Japan Tenant Bug List" (next Sl no = 12), evidence: the sample PDF + field screenshots (failing field next to the
bill block, section title visible) uploaded to the Drive evidence folder, chips in Attachments; re-read the row ~1 min later and
check the chip count.

| Column | Value |
|---|---|
| Job No. | IPA/11/2026-27 |
| MOT | Sea |
| Issue/Bug | An extra House is created from page 2 of the MBL (HKNGO26126471): page 2 is the terms and conditions continuation of the Master bill, not a House document. The pre-alert shows 2 Houses but the sample has only one HBL (GFSLHKG/NGO26003, extracted correctly). The extra House has no Bill No. ("Enter No"), no Shipper / Consignee, Branch not selected, status Job Creation Pending. |
| Reported Date | 26/11/2026 |
| Attachments | JPN-REG-001 - Consolidated.pdf; prealert_expanded.png (the 2 House rows); house_data.png (the extra House showing the MBL terms page) |
| Type | Bug |
| Status / Re-test Status / Re-test By / Comments / Assigned To | blank |
| Reported By | Vigneshwaran S |

## Step 2 – Turn every sheet row into an expected validation (Japan regression)
Read the tab read-only every run. Each row maps to one automated check (config: `config/japan/bug_checks.yaml`, keyed by Sl no;
cases from the IPA: IPA/1 -> SEA-JPN-007, IPA/2 -> SEA-JPN-005, IPA/6 -> SEA-JPN-004, IPA/7 -> SEA-JPN-006, IPA/11 -> SEA-JPN-001):

| Sl | Job | Expected validation (what the regression asserts) | How | Automatable |
|---|---|---|---|---|
| 1 | IPA/1 | Volume of Goods value + unit captured for EVERY container as printed (Doc 276593545); Ctn Pod Ctry = country of the Port of Discharge (JP) | Master/House field check per container | Yes |
| 2 | IPA/1 | (1) Shipper and Consignee Party ID filled; (2) a 2-page House document is ONE document (one row, 2 pages), not two; (3) Freight Payment = FREIGHT COLLECT as printed; (4) Port of destination country = Japan, not India | field check + document list page count | Yes |
| 3 | IPA/1 | Enhancement: Direct BL only when the bill is issued by the carrier, else normal HBL; switch Direct BL <-> House | classification check on a carrier-issued sample; the switch changes data -> manual / on the user's go | Part |
| 4 | IPA/2 | Enhancement: Sea legs from POR/POL/POD/PODel – 4 scenarios: leg count, From/To, vessel+voyage only on POL->POD leg, blank on pre/on-carriage legs | legs read from Nexus vs the bill's boxes (positional extraction) | Yes |
| 5 | IPA/7 | Every document in Document Preview (incl. unmatched) is also in the document list | count + names preview vs list | Yes |
| 6 | IPA/2 | A Party ID created with "Create Party ID" appears in the dropdown | creates data -> only on the user's go | Manual |
| 7 | IPA/2 | Pushed documents visible in CargoWise | needs CW console | Out of scope (report only) |
| 8 | IPA/2 | Controlling Agent in CargoWise | Status Not an Issue | Skip |
| 9 | IPA/7 | Enhancement: House-only Sea push -> only Shipment ID, no Consol ID, no Master draft | push = state change -> on the user's go; then check drafts list | Part |
| 10 | IPA/2 | Carrier Code filled for Master and House | field check (Carrier Code is no longer "held by Nexus": empty = FAIL) | Yes |
| 11 | IPA/1 | Voyage No. = the voyage printed ("639N", not "89 639N") | positional extraction of the vessel/voyage box, exact compare | Yes |
| 12 | IPA/11 | Houses count = HBLs in the sample (1); no House created from an MBL continuation page (extra House = FAIL row 'Pre-alert · additional House'); the sample's House is the one validated | House check + Houses count vs page map (`_pages.json`) | Yes |

New rows added later are picked up automatically: a row without a mapped check is listed as "NO CHECK YET" in the report (never silently skipped).

## Step 3 – Re-test logic on every Japan build
For each row with Status in (Resolved, Fixed, Development Completed) and Re-test Status blank:
1. Run its check on the row's pre-alert (validate existing pre-alerts too; never resend a sample already in the tenant).
2. PASS -> proposed Re-test Status `Resolved`; FAIL -> proposed `Not resolved` with the failing field, document value, Nexus value.
3. Capture field-specific evidence, upload to Drive (`/Japan/<date>/`), show it to the user.
4. Ask the user per row; write Re-test Status, Re-test By and Comments (evidence names) only after the yes. Never change Status
   (dev's column) and never touch other rows.
Rows still In Development: run the check anyway and report it as KNOWN (still failing / now passing – "possibly fixed").

## Step 4 – Report
Run report section "JAPAN BUG SHEET": per row – Sl, Job, check, result, proposed Re-test Status, evidence; plus "NO CHECK YET" rows.
Upload evidence + report PDF to Drive; `./nx log` the outcome.

## Rules (unchanged)
Confirm each bug before adding it; never touch earlier rows except the Re-test columns of re-tested rows after the user's yes; emails
one by one (30 s); deletes only on command; runs headed; "Document says" never blank; no secrets or customer data in the repo.
