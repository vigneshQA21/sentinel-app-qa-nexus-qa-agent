# Individual mapping: cases matched to samples, and the execution plan

Drafted 2026-11-04 for the user's review. Nothing here has been sent. Individual cases send each document as its own email (one by one, 30 s apart; 60 s for REG-011).

## 1. Cases matched to samples

### Air (cases from the Air Single House workbook / coverage tab "AIr Master and House - Single")

| Case | Scenario | Sample (files) | Status |
|---|---|---|---|
| REG-006 | Master + House + Manifest + Debit Note + Invoice + Packing List; Debit Note to Master, rest to House | `samples/REG-006/` FJ-0000518 (6 files: Airwaybill, MA-1, HA-4, IN-6, PL, DN-3) | Runnable now |
| REG-007 | Master + House + Manifest + Delivery Note + Invoice; Delivery Note to House | `samples/REG-007/` (5 files: Air Waybill, Manifest, Invoice 0255210, House ORAE26040499, Delivery Note 009041) | Runnable; shares its shipment with REG-003, delete REG-003's pre-alerts first |
| REG-011 | Master + House + Manifest + random document; the random one must not map | `samples/REG-011/` FJ-0001012 split (Master, House, Manifest) + dummy `Orchid_Meadow_Notes_7Q4X.pdf` | Runnable on request (the Air workbook still says "NO SAMPLE": update it) |
| REG-013 | Master + House + Delivery Note; Delivery Note to House | Reuse REG-007's Air Waybill, House and Delivery Note only | New case; same shipment as REG-007, so run after REG-007's pre-alerts are deleted |
| REG-016 | Master + House + Manifest + Delivery Note + Invoice + Packing List + Shipper Document | none (hypothetical) | Not executable; would need a Shipper Document sample for a shipment that has Delivery Note |
| (new) IND base | Master + House + Manifest + Invoice + Packing List as separate emails | `knowledge_base/.../Individual Mapping/1 M, 1 H, Mani , INV ,PK/` FJ-0000765 (extracted pages: Master, House, Manifest, Invoice, Packing List) | New case, sample available |
| (alt REG-011) | Master + House + Manifest(?) + unclassified document | `.../1 M , 1H , 1Mani , Unclassified document/` FJ-0001163 (Master AWB, House AWB, Sample Invoice) | Alternative sample; to be confirmed what its "unclassified" file is |

### Sea (cases from the coverage tab "SEA Single Master and House -QA"; no Sea individual set exists yet)

| Case | Scenario | Sample to reuse (split into separate PDFs) | Pre-alert to delete first |
|---|---|---|---|
| SEA-SH-029 | MBL and HBL as separate PDFs in one email | SEA-REG-002 shipment, FJ-0001497 (MBL p1, HBL p2) | SEA-REG-002 (IPA/2396) |
| SEA-SH-030 | MBL, HBL, Invoice, Packing List as separate PDFs in one email | SEA-REG-001 shipment, FJ-0001380 (MBL p3, HBL p4-17, Invoice, Packing List) | SEA-REG-001 (IPA/2386) |
| SEA-SH-031 | HBL + Invoice + Packing List first, MBL sent later | SEA-REG-001 split again, two emails | after SEA-SH-030's pre-alert is deleted |
| SEA-SH-007 / 020 / 021 | Individual documents map to the same shipment; supporting documents sent later map to the existing House; a matching email continues the thread | SEA-REG-001 split, several emails (documents first, Invoice/Packing List later) | after SEA-SH-031's pre-alert is deleted |
| scan variant | Individual mapping with scanned pages | SEA-REG-007 (FJ-0001393) or SEA-REG-008 (FJ-0001498): scanned page as its own file | their consolidated pre-alerts (IPA/2416, IPA/2417) |

## 2. Execution plan

Rules for every step: the user deletes the old pre-alerts of the shipment first (the agent never deletes); one shipment at a time; headed browser; one email at a time; wait 3 to 7 minutes for Nexus; capture the Pre-Alerts page and expanded row; bug candidates stay pending until the user says yes; each bug row carries field-specific captures and the pre-alert PDFs.

| Step | Cases | Before sending | Send | Validate |
|---|---|---|---|---|
| 0 | Prepare | Confirm the case list, delete nothing yet; refresh the workbooks (REG-011 sample entry) | | |
| 1 | Air REG-006 (FJ-0000518) | Old REG-006 pre-alerts (IPA/2361 and its follow-ups) deleted | `./run_regression.sh REG-006` (6 emails) | `./nx validate --cases REG-006`, then master, house, docs |
| 2 | Air REG-011 (FJ-0001012 + dummy) | REG-011 pre-alerts (IPA/2374-2377) deleted | `./run_regression.sh REG-011` (60 s gaps) | `./nx validate --cases REG-011` (the dummy must stay unmapped) |
| 3 | Air REG-003 then REG-007 | Delete REG-003's pre-alerts (IPA/2373) before REG-007 | `./run_regression.sh REG-007` (5 emails) | validate, master, house, docs |
| 4 | Air REG-013 | REG-007's pre-alerts deleted | 3 emails (Master, House, Delivery Note) | mapping: Delivery Note in House |
| 5 | Air IND base (FJ-0000765) | no pre-alert for FJ-0000765 in Nexus | 5 emails | mapping and data |
| 6 | Sea SEA-SH-029 (SEA-REG-002 shipment) | SEA-REG-002 pre-alert (IPA/2396) deleted | MBL and HBL in one email, as separate files | mapping |
| 7 | Sea SEA-SH-030 (SEA-REG-001 shipment) | SEA-REG-001 pre-alert (IPA/2386) deleted | four files in one email | mapping, Invoice and Packing List data |
| 8 | Sea SEA-SH-031, then 007 / 020 / 021 | previous run's pre-alert deleted | HBL + Invoice + Packing List, wait, then MBL | mapping after the second email |
| 9 | Record | | | `./nx runreport`, `./nx casedoc`, workbook results, progress log, Zoho update |

Time: about 10 to 15 minutes per case (emails x 30 s, then 3 to 7 minutes in Nexus, then the checks).

## 3. What has to be built first

- Air: nothing for steps 1 to 3 (already runnable). Steps 4 and 5 need workbook rows and sample folders.
- Sea: an individual set (`SEA-IND-nnn`): split the consolidated PDFs by page role, stage them in `samples/SEA-IND-nnn/`, workbook rows with the expected mapping, and a multi-email plan for SEA-SH-031 / 007 / 020 / 021 (send, wait, send the later document).
- Checks: the existing validate commands work per case; for several emails in one pre-alert the agent already reads follow-ups from the Others tab.
