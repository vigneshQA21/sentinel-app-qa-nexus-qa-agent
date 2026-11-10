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
9. **Pre-send bill check (standing order, 10-Nov-2026).** Before EVERY send, look the case's bill numbers (`state/case_bills.json`, read from the sample) and its FJ reference up in Nexus: list search "Bill No" and "Email Subject", Pre-Alerts and Others tabs (`./nx preflight <cases>`; `run_regression.sh` runs it before sending). If the sample already exists in Nexus (any row, the agent's or someone else's) do NOT send: list each row (IPA, subject, sender, received, bill) and ask the user for a manual yes to delete; delete only on that yes (`./nx delete` for the agent's own rows, other people's rows only when the user names them). If nothing exists, send automatically without asking. A shipment that already exists absorbs the new email, so sending anyway tests nothing.

## Scope (air, single house)
Consolidated: REG-001, 002, 005, 009. Individual: REG-006, 007. Excluded: REG-003 (same shipment as 007), REG-016 (hypothetical, no sample: not executable), REG-004 and multi-house. REG-011 runs on request: its sample is FJ-0001012 split into Master/Manifest/House plus a dummy unclassified document (own shipment, no collision), `./run_regression.sh REG-011 --validate`; the check is that the dummy is not mapped. Sea cases are not automated. Change scope only if the user says so.

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
