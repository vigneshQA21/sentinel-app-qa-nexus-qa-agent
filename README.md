# Nexus Pre-Alert Automation Agent

Automates the pre-alert flow end to end:

1. **Gmail** – finds new pre-alert emails and forwards them (all attachments) to `prealert.nexus@unifo.in`, then labels them `Nexus/Forwarded`.
2. **Nexus session** – reuses a saved login session; re-logs in only when it expires.
3. **Find** – waits for the pre-alert to appear in the user's Nexus list (by HAWB or MAWB).
4. **Classification** – checks Master (MAWB/MBL), House (HAWB/HBL), Commercial Invoice and Shipper document are classified.
5. **Shipper data** – validates fields, applies safe autofixes and per-shipment corrections, saves the edits in Nexus and re-reads them to confirm.
6. **TMS push** – snapshots the data, pushes the XML to the TMS, waits for approval.
7. **XML check** – copies the approved XML and reconciles every mapped field against the snapshot.
8. **Report** – `runs/_reports/<timestamp>/summary.html|csv|results.json`, with screenshots and the XML under `runs/<date>/<HAWB>/`.

A shipment is never pushed twice: status is tracked in `state/agent.db`, and a pushed shipment resumes at the approval step on the next run.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env                                    # fill in NEXUS_BASE_URL etc.
```

**Gmail API (one time):** in Google Cloud Console create a project → enable *Gmail API* → OAuth client ID of type *Desktop app* → download JSON to `secrets/gmail_credentials.json`. The first run opens a browser to authorise the mailbox that receives pre-alerts; the token is saved to `secrets/gmail_token.json`.

**Nexus session (one time, and whenever it expires without stored credentials):**
```bash
python -m nexus_agent login
```

## Fill in for the real Nexus

| File | What to change |
|---|---|
| `config/selectors.yaml` | Every selector, taken from the real Nexus screens (`playwright codegen <nexus-url>` helps). Shipped values match the mock. |
| `config/settings.yaml` | `nexus.base_url`, Gmail `query`, `references.hawb_pattern`, timeouts, `xml_capture.mode` (text / download / clipboard). |
| `config/rules.yaml` | Document type labels exactly as Nexus shows them; mandatory shipper fields and formats. |
| `config/xml_mapping.yaml` | XPath for each field, from a real approved TMS XML sample. |
| `corrections/<HAWB>.yaml` | Optional per-shipment shipper fixes, e.g. `shipper_city: Tiruppur`. |

## Run

```bash
python -m nexus_agent run --dry-run                 # checks only: no forward, no edit, no push
python -m nexus_agent run                           # full flow
python -m nexus_agent run --no-gmail --refs UNF1001 # (re)process specific references
python -m nexus_agent run --headed                  # watch the browser
python -m nexus_agent forward                       # Gmail forwarding only
```

Schedule `python -m nexus_agent run` every 10–15 minutes (Windows Task Scheduler or cron). Exit code 0 = nothing needs attention, 2 = at least one shipment needs review.

## Statuses

| Status | Meaning | Pushed? |
|---|---|---|
| PASS | All checks passed and XML matches | Yes |
| NOT_RECEIVED | Not in Nexus yet – retried next run | No |
| CLASSIFICATION_FAIL | A required document is missing/unclassified | No |
| NEEDS_REVIEW | Shipper data fails a rule with no correction | No |
| EDIT_FAIL | An edit did not save | No |
| APPROVAL_PENDING | Pushed, waiting for approval – re-checked next run | Yes |
| REJECTED | TMS push rejected in Nexus | Yes |
| XML_MISMATCH | XML differs from Nexus data (field diff in report) | Yes |
| ERROR | UI error after retries (screenshot + HTML saved) | No |

## Try it without Nexus

```bash
python mock_nexus/app.py                 # mock Nexus on http://127.0.0.1:5055 (demo/demo)
NEXUS_MOCK=1 NEXUS_USER=demo NEXUS_PASSWORD=demo python -m nexus_agent run --no-gmail --refs UNF1001 UNF1002 UNF1003 UNF1005
python -m pytest -q                      # 11 tests incl. end-to-end against the mock
```
