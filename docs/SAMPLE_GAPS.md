# Sample gaps – regression scenarios blocked by missing samples

Status: 27 Nov 2026. One section per tenant. Re-check whenever new samples arrive (see "How to re-check").
Case IDs and document types only: no customer names, bill numbers or document contents in this public repo.
The full version with shipment references is the Google Doc "Nexus Pre-Alert Regression – Sample Gaps (India, Japan, Dubai)"
in the QA lead's Drive, and `samples/<tenant>/_inbox/SOURCES.md` (local, gitignored) maps every sample to the email it came from.

## Summary

| Tenant | Blocked scenario groups | Main sample need |
|---|---|---|
| India | 6 | Sea shipments with their own Sea Manifest, Delivery Note, Shipper Document; multi-House Sea with per-House documents; Direct BL Sea data variants; one complete 7-document Air set |
| Japan | 6 | More Air import samples (one Air shipment so far), Sea Direct BL, Sea third-country |
| Dubai | 4 | Missing Masters / invoices of the sets received, plus multi-House, shipper-document, third-country, debit-note and courier sets |

## India

| Scenario (test case) | Why it can't run | Sample needed |
|---|---|---|
| REG-016: Master + House + Manifest + Delivery Note + Invoice + Packing List + Shipper Document | No single shipment holds all seven; mixing shipments makes the test meaningless | One Air shipment with all 7 documents |
| Sea Manifest mapping (SEA-SH-002/008); Sea Multi-House SEA-MH-002, 008, 010 | No Sea Manifest belonging to one of our Sea shipments | A Sea shipment (single- and multi-House) with its own Sea Manifest |
| Sea Delivery Note (SEA-SH-012); Sea Shipper Document (SEA-SH-013) | No Sea sample contains them | A Sea shipment with a Delivery Note; one with a Shipper Document |
| Multi-House with per-House documents (SEA-MH-004, 005, 006) | No multi-House sample with documents per House | MBL + 2 HBLs, each with its own Invoice / Packing List / Delivery Note; one Invoice without an invoice number |
| Direct BL Sea (TC-DBS-002 to 013) | Needs specific data | Direct BL Sea bills with Shipper name variants vs the Agent Dump, co-loader info, FLYJAC / LOGISTEED consignee, a non-India POD, several Indian PODs |
| COA / Dock Report (SEA-SH-026/027) | Manual Documents-section tests | None (manual) |

Also no sample at all: AMF-005 (Master + House + Certificate of Origin). Partly blocked: REG-005 (sample has no Manifest / Shipper Document),
SEA-REG-006 (screening finds no MBL), SEA-REG-008 (HBL is a scanned page), REG-002 / REG-009 (scans: screening reads are REVIEW-level).

## Japan

One Air shipment received (26 Nov, via the product team): MAWB + HAWB + Manifest in one email, the agent's Debit Note on an INVOICE label with the
LOGISTEED name in a second email (it is IPA/16 in the Japan tenant, Japan sheet Sl 21). It covers: consolidated Master + House + Manifest,
Debit Note on an Invoice label -> Master (Sl 19 rule), Debit Note in a later email, multi-leg routing, individual sends by splitting.
LJP's import team is still gathering Air samples. Runnable now as JPN-AIR-001 (first email) and JPN-AIR-002 (Debit Note email), 27 Nov 2026.

| Scenario (follows the India Air test cases) | Why it can't run | Sample needed |
|---|---|---|
| Air with the shipper's Commercial Invoice / Packing List / Shipper Documents / PO / Delivery Note | The Air sample has none | An Air shipment with the shipper's CI + PL (+ PO / Delivery Note) |
| Air multi-House (1 MAWB + several HAWBs) | One HAWB only | A consol MAWB with 2+ HAWBs and their documents |
| Air Direct Master; Air third-country | No such sample | A Direct Master AWB; an Air shipment with a non-Japan destination |
| Air consol / break-bulk from other forwarders (instructions + customs-classification documents in one file) | Not received; LJP: the largest share of Air import file creation | The samples LJP's import team is gathering |
| Air scanned or unclassified document | No such sample | A scanned AWB set; a pre-alert with an unrelated attachment |
| Sea Direct BL; Sea third-country | No such Japan Sea sample | A Japan Sea Direct BL; a Sea shipment with a non-Japan POD |

Sea samples cover all 9 Japan shipments. Not sendable (not PDF): SEA-JPN-002 booking .xlsx, 004 .xlsx, 005 INV/PL .xls + photo (so 005's
invoice / packing-list scenario is not covered), 007 progress .xlsx.

## Dubai (16 sets, cases SEA-DXB-0nn / DXB-0nn)

| Scenario | Why it can't run | Sample needed |
|---|---|---|
| Air 1 Master + more than 3 Houses; Air 1M + 1H with Shipper Documents | Not in any set | Requested from the Dubai office (19, 20, 26 Nov) |
| Complete third-country set (Air or Sea) | The Air third-country set (DXB-011) has no Master; no Sea third-country | Air third-country with its MAWB; a Sea third-country set |
| Complete agent Debit Note set; Courier | SEA-DXB-012 has the Debit Note but no MBL; no courier sample | The SEA-DXB-012 MBL; a courier pre-alert |
| Invoice checks for SEA-DXB-001, SEA-DXB-002, DXB-007, DXB-010, DXB-013 (House) | Invoices never received (DXB-010's 'CIPL' file holds the packing list twice, no invoice) | Their Commercial Invoices |

Masters never received: DXB-005, DXB-007, DXB-009, DXB-011. DXB-003's MAWB copy is an .xls only.

## Executable with existing samples (not built yet)

Built by splitting a sample, leaving a document out, or sending in separate emails:
- India: Sea individual / separate-email sends (SEA-SH-007, 020, 021, 029-031); Sea invoice-only (SEA-SH-003/010, from SEA-REG-005); documents
  arriving later; Missing-Docs alerts (Master only / House only); invoice from another shipment (SEA-SH-023); duplicate shipment (SEA-SH-018,
  on purpose, needs a go); Sea Multi-House basic / separate emails / unrelated invoice (SEA-MH-001, 007, 009); AMF-005 if a Master exists for the
  sample holding the Certificate of Origin (check).
- Japan: Sea multi-House (SEA-JPN-003: two Houses in one telex release); invoice / packing list for SEA-JPN-005 only if the .xls is converted.
- Dubai: separate-email and consolidated variants of the 16 sets; Master arriving later (DXB-008); two HAWBs of one MAWB without the MAWB (check);
  Direct Master (DXB-003, DXB-010), Direct BL (SEA-DXB-015), Air manifest (DXB-013).

## How to re-check

1. Expected documents per case: `Document Combination` / `Expected Mapping` in each tenant's workbook (`knowledge_base/<tenant>/testcases/`),
   India Sea workbook tab "Not yet runnable", India coverage workbook ("Test coverage and Test suite (AIR and SEA)": Not Executed rows).
2. What the sample really holds: the send-time screening in `runs/<tenant>/_reports/suite_*.csv` (column `screening` / `warnings`),
   the page maps `samples/<tenant>/<CASE>/_pages.json`. The automatic page classifier alone over-reports gaps on scanned or label-less bills.
3. What Nexus said was missing: its auto-replies to the test emails ("The master document (MAWB/MBL) is missing", "Missing invoice for House bill(s)").
4. Sample requests and answers: the sample-request threads with the tenant offices (Dubai: Direct BL / Direct Master confirmations, 23 Nov).
