---
name: nexus-regression
description: Run and validate the Nexus pre-alert E2E regression (send test emails, wait for Nexus, check mapping and every field against the source PDF, triage bugs). Use for "execute AIR_SINGLE_HOUSE_DAILY", "run REG-001", "validate master/house/docs", "retrigger", bug-sheet logging, or questions about regression results.
---

# Nexus regression

Project: `/home/unifo/Downloads/nexus_agent`. Always run from the project folder with `./nx` or `./run_regression.sh` (they use the project's own Python). Full command reference: `regression_prompts/EXECUTE_CMD.md`. Day-by-day state: `docs/PROGRESS_LOG.md` (read the top first). Overview: `README.md`.

## Working rules (never skip)
1. **Retrigger only on request.** Never send or resend regression emails until the user says "retrigger" / "go". Duplicates in Nexus are costly. Dry-run first.
2. **Ask once before sending:** "Have the previous pre-alerts for these shipments been deleted in Nexus?" If not confirmed, send nothing. (Old pre-alerts make new emails land in *Others* as duplicates.)
3. **Delete in Nexus only on the user's command**: when the user says delete a case (e.g. "SEA-REG-001 delete") run `./nx delete <case>` at once (only that case's agent-tagged pre-alerts, Pre-Alerts + Others, individual follow-ups included). Never delete on your own initiative and never touch other people's pre-alerts of the same shipment.
4. **Bug sheet: confirm each bug.** Nothing goes to the UAT sheet without an explicit yes for that specific bug. `./nx bugs` asks y/n/s. Never touch, comment on or change the status of earlier bugs; only log current findings the user confirms.
5. **Always capture Pre-Alerts screenshots** (Pre-Alerts page + expanded row) on every check; they are archived so nothing is overwritten.
6. **Update docs after each piece of work:** `./nx log "what changed"` (PROGRESS_LOG.md), plus EXECUTE_CMD.md / README when commands or scope change, without being asked.
7. **No secrets in this skill or the repo** (the repo is public): no credentials, tokens, customer data.
8. **Chips must be verified (standing order).** After ANY write that adds Drive chips to the bug sheet (File Name, Re-test jobs or any cell), re-read the cell's chip data (`chipRuns`, not just the text) about a minute later, check the number of chips against what was written, re-add a missing chip, and tell the user the count. Other testers edit the sheet at the same time, so a chip can disappear. Never report evidence as attached without that check.
9. **Pre-send check (standing order, 10-Nov-2026).** Before EVERY send, two look-ups in Nexus (list search, Pre-Alerts and Others): first the case's bill numbers (`state/case_bills.json` + the HAWB of an Air sample, plus its FJ reference), then the IPA numbers the case had on earlier runs (`./nx preflight <cases>`; the suite runs it before sending). Sample not in Nexus: send automatically, no question. Sample exists (any row, the agent's or someone else's): do NOT send that case, but DO NOT STOP the run: the other cases go on, the blocked case is written to `state/pending_approval.json`, and I tell the user which rows (IPA, subject, sender, received) need an approval. On the user's yes, in the middle of the run: delete the approved rows (`./nx delete <CASE>` for the agent's own rows, `./nx delete IPA/nnn/2026-27` for a row the user named) and execute that case with its own `./run_regression.sh <CASE> --validate` while the first run continues (sends are serialised with a 30 s gap across runs). Never delete a row nobody approved. A shipment that already exists absorbs the new email, so sending anyway tests nothing.

## Scope (air, single house)
Consolidated: REG-001, 002, 005, 009. Individual: REG-006, 007. Also built and run: Air multi-house MH-001..004 (`./nx mh-phase`, `./nx validate-mhfields`), Air manifest scenarios AMF-001..008, Air Direct BL DBL-001 (`./nx validate-directbl`, XML via `--xml`; points 5, 7 and the edit / negative cases are EXCLUDED for now), Sea SEA-REG-001..009, SEA-MH-001, SEA-RT-270. Excluded: REG-003 (same shipment as 007, runs after the user deletes 007's pre-alerts), REG-016 (out of scope, no sample). REG-011 runs on request (the user confirms later): its sample is FJ-0001012 split into Master/Manifest/House plus a dummy unclassified document (own shipment, no collision), `./run_regression.sh REG-011 --validate`; the check is that the dummy is not mapped. Data checks work Nexus field -> document and sort every field into PASS / FAIL (matched before, not now) / DISCUSSION NEEDED; nothing is a bug until the user confirms. Drive evidence uploads automatically after every run. Change scope only if the user says so.

## Daily tag: "Execute AIR_SINGLE_HOUSE_DAILY"
Open `regression_prompts/air/AIR_SINGLE_HOUSE_DAILY.md` and follow its prompt step by step (pre-checks -> dry-run -> wait for explicit go -> execute -> verify). 15 emails, ~25 min.

## Commands
| Goal | Command |
|---|---|
| Full run for a case | `./run_regression.sh REG-001 --validate` |
| Several cases | `./run_regression.sh REG-001 REG-002 --validate` / `air-daily` |
| Send only | `./run_regression.sh REG-001` (preview: `--dry-run`) |
| Re-check without sending | `./nx validate` (mapping), `validate-master`, `validate-house`, `validate-docs [--only invoice]` |
| Bug candidates | `./nx bugs --list` (read-only), `./nx bugs` (asks per bug), `./nx bugs --check-sheet` |
| History / docs | `./nx history`, `./nx casedoc`, `./nx cases`, `./nx log "note"` |
| Session expired | `./nx login` (log in by hand, close window) |
| Tests | `.venv/bin/python -m pytest -q` |

Timing: T+0 send, T+3:00 first look, poll every 20 s until T+7:00, then NOT_RECEIVED. Settings in `config/settings.yaml`.

## Data comparison rules (document <-> shipment data) — the user's standing rules, 13-Nov-2026
Goal: every value the source document prints for a field Nexus holds must be in the Nexus shipment data. The document is the truth.
1. **Classify every field** as one of: MATCH (in both, equal), **MISSING** (the document prints it, Nexus is empty), **MISMATCH** (both have a value, they differ), NOT IN DOCUMENT (Nexus has a value, the document prints none: review), HELD BY NEXUS (IDs, status: no document value), NOT_VERIFIABLE (the document value cannot be read, e.g. a scan: never a pass).
2. **Always show both values** ("Document says" and "Nexus shows"). Never leave "Document says" blank for a MISSING or MISMATCH row: read the value from the bill (by block / column position, not joined text). If it cannot be read, say so.
3. **No false alarms.** Before reporting MISSING, name the Nexus block by its own viewer heading (Consignee / Notify Party / For Delivery Details ...) and the document block by its box heading and position. `SAME AS CONSIGNEE`, and an empty block the bill has no party for, are not MISSING. Formatting-only differences (case, punctuation, spaces, address lines joined, thousands separators) are MATCH. A real difference (e.g. K vs KGS, 2.683 vs 2,683) is MISMATCH.
4. **Bug probability.** Every MISSING / MISMATCH finding gets a likelihood of being a real bug, estimated from the pattern of earlier findings in the bug sheet and the local decisions (`bugs` table): P = (real + 1) / (decided + 2) per (nature, document, field); recompute from the data every time, never hard-code. Show the basis ("real 16 of 18 earlier MISSING findings"). The probability only orders the review list; it is not a verdict, and nothing goes to the bug sheet without the user's yes, priority and evidence.
   - Baseline observed 13-Nov-2026 (204 decided candidates, 61 real = 30%): MISSING in Nexus real 16/18 (~85%); MISMATCH real 45/186 (~24%); by document: Master 4/48 (~10%), House 32/113 (~29%), Mapping 8/19, Manifest 2/3, Packing List 2/3, Others tab 3/3; by field: Flight Number 3/4, Postal Code 4/13, Name 4/14, Address 5/29, Unit 0/5, Consignee 0/4, Carrier Name 0/4, unlabelled fields 0/7. Reading: a field missing in Nexus is very likely a bug; a differing name/address/unit is usually a format or OCR difference.
5. **Implemented as the standard for Air and Sea (13-Nov-2026):** `nexus_agent/stdcompare.py` (classes), `bugprob.py` (probability; `./nx patterns` refreshes it from the sheet statuses + your decisions), `docvalue.py` (document boxes read by position), party blocks named by the Nexus viewer heading (`uat.read_panel_inputs`, `map_master_panel` / `map_house_panel`), `sea_check.compare_sea` (MISSING only when the bill prints the box; Notify Party / For Delivery are their own sections; `SAME AS CONSIGNEE` is fine; an extra empty slot of a filled label is INFO), and the run report (Class + Bug likelihood columns, most likely bug first). `./nx bugs` shows Class and Bug likelihood per candidate. The goods description is not read by position (reported MISSING with the bill page).
6. Order the review list by probability (high first) and group the low-probability ones; say what was verified and what is only the checker's wording ([[verify checker FAILs before listing]]).

## Verdicts
PASS = matches the document. FAIL = differs (bug candidate). REVIEW = partial match, check by eye (bug candidate). INFO = data Nexus holds itself / empty with nothing to compare. NOT_VERIFIABLE = value unreadable from the document (never a pass). KNOWN = already logged or "not a bug"; visible but does not fail. "possibly FIXED" = a logged bug's field now matches.

## Evidence
- `runs/<date>/<case>/`: screenshots + `archive/<time>_<IPA>_<name>.png` + `trace_<time>_<IPA>/index.html` (numbered screenshots, "Probable root cause" hints; hints are not verdicts).
- `runs/_reports/`: suite / validate / master / house / manifest / invoice CSVs.
- The source document is the truth; nothing is hard-coded per sample.

## Typical troubleshooting
- "Nothing was sent. Nexus session expired" -> `./nx login`.
- "no pre-alert for REG-xxx" -> not there after 7 min or in *Others* as a duplicate; delete old pre-alert (user does it), re-run on request.
- Odd differences -> someone may have edited the pre-alert in Nexus; re-run on a fresh one.
- Google 403 -> enable Sheets/Drive API, then `./nx bugs --check-sheet`.
