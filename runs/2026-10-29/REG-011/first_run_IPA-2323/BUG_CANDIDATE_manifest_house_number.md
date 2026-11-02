# REG-011 bug candidate: Manifest house number read wrongly, House draft and extra Direct BL House

**Status: NOT in the UAT bug sheet.** Kept locally as a pending candidate. To be confirmed by the user after the re-execution of REG-011 (same order, 60 s gap). Priority: not decided.

## What was seen (first run, 29-Oct-2026, Nexus job IPA/2323/2026-27)
The pre-alert row lists four shipment lines instead of two:

| Record type | Bill No. | Shipper / Consignee | Status text (cut off on screen) |
|---|---|---|---|
| Master | 157-69714304 | ITG AIR AND SEA GMBH / LOGISTEED INDIA PVT. LTD. | CW Sync Pending |
| House | FRA - 6007 5340 | LINDAUER DORNIER GMBH / UFLEX LIMITED | Invoice Mapping Pending |
| **House draft** | **6007 5340 1** | empty (red) | "From manifest — requir…" |
| **House** | **157-69714304** (the Master's number) | ITG AIR AND SEA GMBH / LOGISTEED INDIA PVT. LTD. | "Direct BL — house fro…" |

Missing Docs column: "House, Invoice". Unresolved Documents: 1 (the dummy, Unclassified: expected). In the House viewer of the 157-69714304 row, the page shown is the **Air Cargo Manifest**, labelled HAWB, with shipper ITG AIR & SEA (Martinistrasse 33, Bremen) and consignee Lindauer Dornier (postal code empty).

## What the documents say
- House document: house number `FRA - 6007 5340`, MAWB `157 - 6971 4304`.
- Manifest line: `FRA-6007 5340 1 SPARE PARTS FOR FILM STRECHING MACHINE 172,0 BLR`. The trailing `1` is the piece count.
- Nexus Manifest data (manifest_data CSV): Air Waybill No = `6007 5340 1` (the `FRA-` prefix is dropped and the piece count is glued on).

## Probable cause (a hypothesis, not confirmed)
Nexus reads the manifest house number as `6007 5340 1`. It does not equal the House number `FRA - 6007 5340`, so the manifest line cannot be matched to the real House. Nexus then creates a House draft from the manifest and, apparently, a Direct BL House from the Master number. In REG-006 and REG-007 (plain house numbers such as FLD6445, ORAE26040499) no draft or extra House appeared.

## Expected
One Master and one House (`FRA - 6007 5340`). The manifest line matches that House. No House draft and no extra House numbered with the Master's number.

## How the emails were sent (first run)
Gmail API from vigneshwaran.s@unifo.in to prealert.nexus@unifo.in, one email per document, 30 s apart, order House, Manifest, Master, dummy. Subject: `REG-011 | QA agent trigger / Don't delete / Regression testing | Pre-Alert FJ-0001012 | INDIVIDUAL | <type>`.

| Sent at | Type | File | Gmail message id |
|---|---|---|---|
| 18:25:05 | HOUSE | FJ-0001012 - House.pdf | 1a187ba6d6d873b5 |
| 18:25:36 | MANIFEST | FJ-0001012 - Manifest.pdf | 1a187bae8d2658da |
| 18:26:08 | MASTER | FJ-0001012 - Master.pdf | 1a187bb6597406d7 |
| 18:26:40 | DOCUMENT | Orchid_Meadow_Notes_7Q4X.pdf | 1a187bbe057253f3 |

Nexus made one entry per email: IPA/2322, 2323 (the pre-alert), 2324, 2325 (the other three are "Follow up of IPA/2323" in the Others tab). Pre-alert appeared 184 s after the last email.

## Evidence (this folder)
- `screenshots/user_screenshot_prealert_row_4_shipment_lines.png`: the user's screenshot of the expanded pre-alert row (the four lines).
- `screenshots/182500_IPA-2323-2026-27_prealert_expanded.png`: the agent's capture of the same row, with the Unresolved Documents table.
- `screenshots/182500_IPA-2323-2026-27_parent_House.png`: viewer of the House (157-69714304) showing the Manifest page as HAWB.
- `screenshots/182500_IPA-2323-2026-27_parent_Master.png`, `_parent_Manifest.png`, `_prealerts_list.png`, `_unresolved_row.png`, `_list.png`: the other captures of the run.
- `screenshots/others_tab_IPA-2322_2324_2325.png`: the follow-up entries.
- `screenshots/182500_IPA-2323-2026-27_master_data.png`, `_house_data.png`, `_manifest_data.png`: data panels.
- `trace/index.html`: numbered screenshot trace of the whole check.
- `reports/`: validate, suite, master / house / manifest data CSVs, the run report and the full send-and-validate log.
- `samples_sent/`: the four PDFs exactly as sent.

## Re-test plan
1. User deletes IPA/2322, 2323, 2324, 2325 in Nexus.
2. Send REG-011 in the order House, Manifest, Master, dummy, 60 s apart.
3. After about 3 minutes check the pre-alert row: how many shipment lines, whether a House draft or a Direct BL House appears, and what the Manifest shows as its house number.
4. Archive the second run's evidence next to this folder (second_run_...), then the user decides whether to log it, and with what priority.

## Re-execution result (29-Oct-2026, second run, Nexus job IPA/2326/2026-27)
Evidence: `../second_run_IPA-2326/` (same layout as this folder).

Emails sent one by one, 60 s apart, in the order House, Manifest, Master, dummy (18:45:27, 18:46:29, 18:47:31, 18:48:34; Gmail message ids 1a187cd105656536, 1a187ce049696793, 1a187cef921d26fc, 1a187cfea3e3390f). Same four files as the first run. Pre-alert appeared 185 s after the last email. Follow-ups in Others: IPA/2327, 2328, 2329.

| | First run (IPA/2323, 30 s gaps) | Second run (IPA/2326, 60 s gaps) |
|---|---|---|
| Shipment lines | Master, House, **House draft (6007 5340 1)**, **House 157-69714304 (Direct BL)** | Master, House (FRA - 6007 5340) only |
| Missing Docs | House, Invoice | Invoice (expected: no invoice in this case) |
| Unresolved | 1 Unclassified (the dummy) | 1 Unclassified (the dummy) |
| Manifest data | PASS 8, Air Waybill No `6007 5340 1` | PASS 8 |
| Master / House data | Master FAIL 2, REVIEW 1; House FAIL 2, REVIEW 2 | same counts |

**Reading:** the House draft and the extra Direct BL House did NOT appear in the second run, with the same four documents. So the problem is not reproducible every time. It looks like the intermittent grouping behaviour seen before (challenge 1 in docs/CHALLENGES.md), possibly tied to the email order/timing of the first run (House, Manifest, Master with 30 s gaps), but one re-run is not enough to say so. The manifest house number in Nexus's own manifest data is the same `6007 5340 1` in both runs, so that part alone does not create the extra lines.

**Candidate status: still pending, not in the bug sheet.** The user decides whether to log it (as an intermittent issue, with both runs as evidence), re-run once more, or drop it.

## Why the first run got the extra lines (comparison of the two runs, 29-Oct-2026)
Same four files, same order (House, Manifest, Master, dummy). Only the gap differed: 30 s (first run) vs 60 s (second run).

| Email | First run (30 s gaps): Nexus id, received | Role | Second run (60 s gaps): Nexus id, received | Role |
|---|---|---|---|---|
| House | IPA/2322, 06:25:03 PM | **follow-up of 2323** (Others tab) | IPA/2326, ~06:45:27 PM | **the pre-alert** |
| Manifest | IPA/2323, ~06:25:35 PM | **the pre-alert** | IPA/2327, 06:46:28 PM | follow-up of 2326 |
| Master | IPA/2324, 06:26:07 PM | follow-up of 2323 | IPA/2328, 06:47:30 PM | follow-up of 2326 |
| Dummy | IPA/2325, 06:26:39 PM | follow-up of 2323 | IPA/2329, 06:48:32 PM | follow-up of 2326 |

**What the evidence shows:** in the first run the House email (the first one, lowest id 2322) did NOT become the pre-alert. The Manifest email, 32 s later, became the pre-alert (2323), and the House was re-linked to it as a follow-up. In the second run the House email created the pre-alert and the others attached to it in order.

**Probable explanation (inference, not confirmed by Nexus):** with a 30 s gap the Manifest arrived while Nexus was still processing the House email, so Nexus found no pre-alert to attach it to and created its own from the manifest, with a "House draft" for the manifest's house line (`6007 5340 1`). The House was merged in afterwards and the draft stayed. The Direct BL House (157-69714304) most likely came from the Master arriving while this merge was still going on. With 60 s gaps each email was processed before the next arrived. This is the same timing effect as the REG-006 split into two pre-alerts (parallel / short gaps).

**Correction:** an earlier message of mine hinted that the email order might be the cause. The order was identical in both runs, so it is not. The gap is the only difference.

**For the candidate:** the manifest house number read as `6007 5340 1` is the same in both runs, and the second run shows it does not by itself create the extra lines. The issue is Nexus's handling of emails that arrive close together (grouping by arrival timing), not the manifest reading alone.
