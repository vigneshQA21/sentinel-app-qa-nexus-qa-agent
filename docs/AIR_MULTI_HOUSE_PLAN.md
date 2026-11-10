# Air multi-house: cases matched to samples, and the execution plan

Drafted 2026-11-04 for the user's review. Nothing sent. Cases come from the tab "Air Master and Multiple-House -" of `knowledge_base/testcases/Test coverage and Test suite (AIR and SEA) .xlsx` (29 cases, earlier manual status "Pass").

## 1. The one sample we have: FJ-0000088 (`samples/_multi_house_review/air/`)

| Page | Content |
|---|---|
| 1 | Master AWB 098-45997836 (EV Cargo, scanned, read with OCR) |
| 2 | Consol manifest CAE00684799: lists the HAWBs |
| 3 | Job / HAWB list page (lists EVLHR035455, EVLHR035456, EVLHR035465) |
| 4 | House EVLHR035465 |
| 5 | House EVLHR035456 |
| 6 | House EVLHR035456 again (looks identical to page 5: same number and length; to confirm) |
| 7 | House EVLHR035455 |

So: 1 Master, 3 distinct Houses (EVLHR035455, 035456, 035465), a manifest, and a duplicate of one House. No Invoices or Packing Lists.

## 2. Cases matched to FJ-0000088

| Case | Scenario | How FJ-0000088 covers it | Emails |
|---|---|---|---|
| REG-001 / 002 | One Master, 2 / 3+ Houses | Master + 3 Houses (without Invoice/PL: the House documents part of the case is not covered) | 1 consolidated, or split: Master, Manifest, 3 Houses |
| REG-021 | Exactly 1 Master + N valid Houses, no extra House | Expect exactly 3 Houses | same pre-alert |
| REG-022 | Duplicate HAWB upload creates one logical House | Page 6 is a duplicate of page 5 (EVLHR035456) | same pre-alert; expect 3 Houses, the duplicate flagged |
| REG-007 | Exact HAWB-based matching | Each House page carries its own HAWB | same pre-alert |
| REG-014 | Houses uploaded before the Master | Send the 3 Houses first, the Master + Manifest later | 2 emails (split) |
| REG-015 | Add a new House after initial processing | Master + 2 Houses first, the third House later | 2 emails (split) |
| REG-020 | Missing House: its documents do not map elsewhere | Send Master + Manifest + 2 Houses (the manifest still lists the third) | 1 email, split by omission |
| REG-029 / 030 | Reprocess / refresh keeps the hierarchy | Manual UI steps on the processed pre-alert | no email |
| REG-027 | Delete one House after mapping | Manual UI step (the agent never deletes) | no email |

## 3. Cases that cannot run yet (no sample)

Need Invoices / Packing Lists per House or other shipments: REG-001/002 data part, 003 (different combinations per House), 004 to 006 (multiple invoices / packing lists), 008 to 012 (same consignee / shipper / invoice number / filename, overlapping data), 013, 016 to 018, 023 to 026, 031, 032.
What to provide: one Air consolidated PDF with 2 to 3 HAWBs where each House has its own Invoice and Packing List (the base for most of them), plus a second shipment with the same consignee or shipper.
FJ-0000859 is not multi-house (one House, three invoices): it fits REG-004 only if a second House is added.

## 4. Execution plan (after the user confirms the sample)

1. Prepare: user confirms the Houses in FJ-0000088 and the duplicate page; build the Air Multi-House workbook (same layout as the Air daily one), stage the splits in `samples/AIR-MH-nnn/`.
2. Pre-check each time: no pre-alert of MAWB 098-45997836 in Nexus (the user deletes old ones; the agent never deletes).
3. AIR-MH-001 (REG-001/002/021/007/022): send FJ-0000088 as one email; validate: 1 Master, exactly 3 Houses, manifest linked to the Master, duplicate page handled; Master and each House data check (one House at a time).
4. AIR-MH-002 (REG-014): user deletes the previous pre-alert; send the 3 Houses, wait, then Master + Manifest; validate the regrouping.
5. AIR-MH-003 (REG-015): delete; send Master + 2 Houses, wait, send the third House; validate nothing changed for the first two.
6. AIR-MH-004 (REG-020): delete; send Master + Manifest + 2 Houses; validate no document under the wrong House.
7. Manual UI cases (REG-027, 029, 030): the tester performs the action; the agent compares before / after.
8. Record: run report, test-case workbook, bug sheet on the user's yes (field-specific captures, PDFs), progress log, Zoho update.

## 5. What has to be built

- The per-House mapping check: today `validate` reads one Master and one House. It needs to read every House parent and compare the House count and each House's HAWB.
- Air Master / House data checks per House (the Sea check already has a House picker, `NEXUS_HOUSE_BILL`).
- Split staging for FJ-0000088 (by page: Master, Manifest, each House).
