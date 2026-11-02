# Invoice / Packing List "duplicates": what we saw, why, and what changed (2-Nov-2026)

## Short answer
The duplicates come from the REG-002 sample PDF itself, not from the agent. `FJ-0000602 ... deduped.pdf` (10 pages) still holds the
same documents twice: Air Manifest p2 = p3 (identical text), Commercial Invoice HK260810 on p6 and p10 (differ only in one dimension,
0.70m vs 0.57m), Packing List HK260810 on p7 and p9 (differ in weights and dimensions). Nexus now flags the second copy as
"Duplicate" and leaves it under Unresolved Documents. Before row 236 was fixed Nexus classified the Packing List pages as Invoice,
which is why the House showed INVOICEx4 and no Packing List.

## REG-002 over time (pre-alert row "Unresolved Documents" + House Linked list)
| Run | Pre-alert | House Linked (viewer) | Unresolved Documents (row) |
|---|---|---|---|
| 24-Oct 16:16 | IPA/2185 | HAWB, INVOICE x4, SHIPPERDOC | not captured yet (capture added 27-Oct) |
| 28-Oct 10:16 | IPA/2283 | HAWB, INVOICE x4, SHIPPERDOC | 1: AirManifest, Remark "Duplicate" |
| 29-Oct 12:16 | IPA/2301 | HAWB, INVOICE x4, SHIPPERDOC | 1: AirManifest, Remark "Duplicate" |
| 2-Nov 12:32 | IPA/2359 | HAWB, INVOICE, PACKINGLIST, SHIPPERDOC | 3: AirManifest, Invoice, PackingList, all "Duplicate" |

Screenshots: runs/2026-10-28/REG-002/trace_101609_IPA-2283-2026-27/04_unresolved_row.png,
runs/2026-10-29/REG-002/trace_121649_IPA-2301-2026-27/04_unresolved_row.png,
runs/2026-11-02/REG-002/trace_123214_IPA-2359-2026-27/04_unresolved_row.png and 07_parent_House.png (29-Oct 07_parent_House.png for the old view).

## Other cases
| Case | Duplicates? | Note |
|---|---|---|
| REG-001 (7 pages) | No | Invoice x3 = pages 4-6 of a 4-page invoice, Packing List x1, nothing unresolved |
| REG-005 (6 pages) | First run only | IPA/2203 (26-Oct) INVOICEx4 because the PDF held the invoice 3 times; after the sample was de-duplicated INVOICEx2 (Page 1 of 2, 2 of 2) in every run since |
| REG-006, REG-007 | No | nothing unresolved |
| REG-009 (scan) | n/a | Unresolved: 2 unclassified pages, as the test expects |

## Is it a Nexus bug?
Not by itself: the second copy of an identical document is flagged Duplicate by design. Two points to decide:
1. The REG-002 sample should either be de-duplicated (like REG-005) or kept on purpose to test duplicate handling. Not changed.
2. The Invoice and Packing List copies are not identical (different dimensions/weights), so which copy Nexus keeps matters for the data checks.

## New observations in today's run (candidates, nothing logged in the sheet)
- REG-002 Packing List, Date: Nexus shows "HK260810, 10. Aug. 2026"; the document has the invoice number "HK260810-HEIND" on one line and "Invoice date : 10 . Aug . 2026" on another. Nexus appears to put the invoice number into the Date field. First visible today because the Packing List was missing before (row 236).
- REG-007 House (IPA/2367), flight route: Nexus shows Type "direct", Segment 1 To BOM, no Segment 2; the document routes DEL (AI142/15) then BOM (AI441/17), i.e. connecting. 7 field candidates, one defect (route not read from the House). Master Flight Number Al142 (row 248) is still there.
- REG-009 House (IPA/2372), Shipper Postal Code 28461 vs 28451 from the scan: REVIEW only (OCR).
- Fixed or looking fixed: row 236 (REG-002 Packing List now placed in the House), row 230 (REG-001 Packing List Date matches), rows 240, 241, 245 re-tested earlier.
