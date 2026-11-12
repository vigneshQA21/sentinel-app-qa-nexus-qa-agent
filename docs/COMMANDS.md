# Command reference (no Claude needed)

Run everything from the project folder `/home/unifo/Downloads/nexus_agent`. `./nx <command>` runs the agent with the project's own Python (no need to activate `.venv`). `./run_regression.sh` sends cases and optionally validates them. Anything with `--help` explains its flags: `./nx <command> --help`.

Safety rules that apply to every command:
- Nothing is sent to the Nexus mailbox without you starting a send command; send only after the old pre-alerts of those shipments are deleted in Nexus.
- Nothing is added to the UAT bug sheet without your `y` for that bug (`./nx bugs`).
- Nothing is posted to Zoho without your answer at the prompt (`./nx post-update`).
- Nothing is ever deleted in Nexus by the agent.
- Secrets live in `.env` and `secrets/` only; both stay out of git.

## 1. Send test cases (`./run_regression.sh`)

| Command | What it does |
|---|---|
| `./run_regression.sh REG-001` | Sends one Air case to prealert.nexus@unifo.in (one email at a time, 30 s gaps) |
| `./run_regression.sh REG-006 REG-007` | Sends several cases, with a gap between cases |
| `./run_regression.sh air-daily` | The whole AIR_SINGLE_HOUSE_DAILY set (6 cases, about 15 emails) |
| `./run_regression.sh SEA-REG-001` | Sends one Sea case (Sea is send-only in the suite; validate per case, see section 2) |
| `./run_regression.sh sea-daily` | SEA-REG-001 to 008 |
| `... --validate` | After each case is sent: wait 3 min, poll Nexus, check the mapping (Air only) |
| `... --dry-run` | Preview only, nothing is sent |
| `... --no-wait` | No 5-minute gap between cases |
| `... --no-force` | Skip cases that fail screening |

At the end of a real send it also writes today's run report (section 4).

## 1b. Delete the old pre-alerts (before a resend)

| Command | What it does |
|---|---|
| `./nx delete SEA-REG-001` | Deletes every pre-alert of the case in Nexus, in the Pre-Alerts tab and in Others (follow-up emails of individual-mapping cases), via the row menu > Delete. Only subjects that start with `<CASE> |` and carry the agent's tag; other people's pre-alerts of the same shipment are never touched. Screenshots of each row before deleting: `runs/<date>/<case>/cleanup/`. Afterwards the case can be sent again without `--resend` |
| `./nx delete REG-006 REG-011` | Several cases |
| `./nx delete sea-daily` / `air-daily` | The whole set |
| `./nx upload-evidence [--date yyyy-mm-dd] [--dry-run]` | Uploads the day's evidence to Google Drive in one fixed layout: `Regression testing / Nexus Automated Test Evidence / <yyyy-mm-dd> /` with `01 Test runs/<CASE> - <IPA>/` (every screenshot of the checks, named `<HHMMSS>_<name>`, plus a `cleanup` folder for delete evidence), `02 Bugs/` (evidence of the bugs logged that day: new bug rows upload here) and `03 Report/` (`Automated test report <date>.pdf`, replaced as the day goes on). Nothing is overwritten or deleted. `run_regression.sh` runs it at the end of every run. The folder link is kept in `state/drive_evidence.json` |
| `./watch_run.sh [name]` | Follows the regression output live in the terminal you run it in (VS Code terminal): tails the newest log in `runs/_logs/` and switches by itself when a newer run starts; `./watch_run.sh reg002` follows the newest log whose name contains `reg002`. Also a VS Code task: Terminal > Run Task > "Watch regression run". Ctrl+C stops it. Runs the agent starts in the background write their output to `runs/_logs/*.log`, so this shows them |
| `./nx preflight REG-001 SEA-REG-002` | Standing order before every send: looks each case's bill numbers (`state/case_bills.json` plus the HAWB of an Air sample) and its FJ reference up in Nexus with the list search (Bill No and Email Subject, Pre-Alerts and Others). Prints CLEAR (not in Nexus: it can be sent) or BLOCKED with every existing row (tab, IPA, subject, sender, received, what matched, and whether it is the agent's own row). Exit code 3 when blocked. `./nx suite` / `run_regression.sh` run it first and send nothing when a sample exists: you confirm which rows to delete, then it runs again |
| `./nx delete SEA-REG-001 --dry-run` | Lists what would be deleted, deletes nothing |
| `./nx delete SEA-REG-001 --bill ABC123` | Also looks for this bill number (use when the case has no pre-alert of its own to read the bills from). Bill check: the case's bills are read from its own row (kept in `state/case_bills.json`) and searched with Nexus's 'Bill No' filter in both tabs. A row with another subject, or with the case's subject but a bill that is not in the sample PDF, is **not deleted**; it is listed with tab, IPA, subject, sender, received date, bill and reason for you to confirm by hand. Nexus's bill search matches the Master bill (a House bill returned no rows) |

How it deletes: row menu > Delete opens Nexus's **Delete job** dialog ("Delete this job (IPA/... — <subject>) and all of its related or follow-up jobs in the same consol/thread ... cannot be undone"). The command confirms only when the dialog names this IPA and this case id (otherwise it presses Cancel and reports FAILED). Because Nexus also removes related follow-up jobs of the same thread, the output prints the tab counts before and after.
If a delete fails (menu or dialog not recognised, or the row is still listed), it stops, saves a screenshot and reports `FAILED`; nothing else is deleted.

## 2. Check what Nexus did (`./nx validate*`)

All take `--cases REG-001 [REG-002 ...]` (Sea ids such as `SEA-REG-001` work for the data checks), `--wait SECONDS` (how long to wait for the pre-alert) and `--headless` (hide the browser; the default shows it).

| Command | What it checks |
|---|---|
| `./nx validate --cases REG-001` | Mapping: which document sits under Master, House, Manifest, Unmatched, Unclassified, and the Others tab. Also `--ref <HAWB/FJ>` |
| `./nx validate-master --cases REG-001` | Master fields in Nexus against the source PDF |
| `./nx validate-house --cases REG-001` | House fields against the source PDF |
| `./nx validate-docs --cases REG-001` | Manifest, Invoice and Packing List fields (plus Debit Note / Shipper Document where present); `--only manifest invoice packing` to limit |

Each check saves screenshots, a trace folder with an index page (`runs/<date>/<case>/`), CSV reports (`runs/_reports/`) and bug candidates (pending, not logged).

## 3. Bugs (nothing is logged without your y)

| Command | What it does |
|---|---|
| `./nx bugs --list` | Lists the pending candidates, read-only |
| `./nx bugs` | Asks y / n / s for each candidate; on y it writes the row to the UAT bug sheet with the evidence |
| `./nx bugs --check-sheet` | Connects to the bug sheet read-only and checks the header and columns |
| `./nx history` | The bug repeat tracker: each finding, how often it repeats, its status |

## 4. Reports and test-case document

| Command | What it does |
|---|---|
| `./nx runreport [--date yyyy-mm-dd]` | Today's run only: observations, bugs found, earlier bugs that passed. Also writes the HTML report `runs/_reports/runreport_<date>.html` |
| `./nx casedoc --cases REG-001 REG-002` | Writes the validations into the Air test-case workbook (new tab; a backup is made first) |
| `./nx casedoc --cases SEA-REG-001 SEA-REG-002 ...` | The same for Sea: tab `Validations SEA-REG` in the Sea workbook (Air and Sea ids can't be mixed) |
| `./nx cases` | Lists the in-scope cases (Air and Sea) and whether the samples are there |
| `./nx ingest` | Files downloads from `samples/_inbox/` under their test case |

## 5. Zoho update (Cliq group + Sprints task SN-I68)

| Command | What it does |
|---|---|
| `./nx post-update --file state/zoho_update.md --dry-run` | Shows what would be posted, posts nothing |
| `./nx post-update --file state/zoho_update.md` | Shows it, then asks: `y` both, `c` Cliq only, `s` Sprints only, `n` cancel. Asks again if already posted today |
| `./nx post-update` | Builds the update itself from today's `docs/PROGRESS_LOG.md` entries and bugs logged today (detailed, edit before reuse) |
| `./nx post-update --date yyyy-mm-dd` | The same for another day |

Format of `state/zoho_update.md` (your format): line 1 `Update: dd-Mon-yyyy – title`, a blank line, then one plain line per item (no bullets, no stars). In Sprints the heading is shown bold and each line on its own line.

Settings are read from `.env` (names in `.env.example`): `ZOHO_CLIQ_CHAT_ID` (or `ZOHO_CLIQ_WEBHOOK_URL`), `ZOHO_ACCOUNTS_URL`, `ZOHO_SPRINTS_API`, `ZOHO_CLIENT_ID`, `ZOHO_CLIENT_SECRET`, `ZOHO_REFRESH_TOKEN`, `ZOHO_SPRINTS_TEAM_ID`, `ZOHO_SPRINTS_PROJECT_ID`, `ZOHO_SPRINTS_MODULE_ID`, `ZOHO_SPRINTS_ITEM_ID` (the numeric IDs, not P21 / I68). A missing setting is named in the output and nothing is sent. The access token is cached in `state/zoho_token.json`.

If Zoho says `invalid_code` for the refresh token: in the API Console (api-console.zoho.in) open the Self Client, Generate Code with the scopes `ZohoCliq.Webhooks.CREATE,ZohoSprints.comments.CREATE,ZohoSprints.teams.READ,ZohoSprints.projects.READ,ZohoSprints.items.READ,ZohoSprints.settings.READ` (no spaces, no trailing full stop), then within 10 minutes exchange the code (use the `refresh_token` field of the reply, not `access_token`):
```bash
cd /home/unifo/Downloads/nexus_agent && read -rp "Grant code: " CODE && set -a && . ./.env && set +a && curl -s -X POST "$ZOHO_ACCOUNTS_URL/oauth/v2/token" -d grant_type=authorization_code -d client_id="$ZOHO_CLIENT_ID" -d client_secret="$ZOHO_CLIENT_SECRET" -d code="$CODE"
```

## 6. Progress log

| Command | What it does |
|---|---|
| `./nx log "what changed"` | Adds a bullet under today's heading in `docs/PROGRESS_LOG.md` (never changes older entries) |

## 7. Session, sending and processing (lower level)

| Command | What it does |
|---|---|
| `./nx login [--wait SECONDS]` | Opens a browser to log in to Nexus by hand and saves the session (`state/nexus_session.json`); no password is stored |
| `.venv/bin/python scripts/check_session.py` | Prints LOGGED IN or SESSION EXPIRED |
| `./nx suite --cases REG-001 [--dry-run] [--force] [--validate] [--interval S] [--resend]` | What `run_regression.sh` calls: stage, screen and send the sample documents |
| `./nx send-local [--refs ...] [--dry-run] [--force]` | Screens and emails knowledge_base documents to the Nexus mailbox |
| `./nx forward [--dry-run]` | Forwards new Gmail pre-alerts only |
| `./nx run [--refs ...] [--no-gmail] [--dry-run] [--headed]` | Processes pre-alerts end to end (the original agent flow) |

## 8. Tests

```bash
.venv/bin/python -m pytest -q                      # all tests
.venv/bin/python -m pytest -q tests/test_zoho_post.py
```

## 9. Where things are

| What | Where |
|---|---|
| Settings and selectors | `config/settings.yaml`, `config/selectors.yaml` |
| Secrets (not in git) | `.env`, `secrets/`, `state/` |
| Evidence and traces | `runs/<date>/<case>/` |
| CSV reports, run report | `runs/_reports/` |
| Live status page of a running command | `runs/_live/index.html` (opens by itself; `NEXUS_NO_LIVE=1` turns it off) |
| Run logs | `runs/_logs/` |
| Day-by-day log | `docs/PROGRESS_LOG.md` |
| Older command notes by tag | `regression_prompts/EXECUTE_CMD.md` |

## Air manifest / order scenarios (AMF-001 ... AMF-006)
One sample is sent in different orders, one phase at a time. The same shipment cannot be in Nexus twice: delete the previous phase's pre-alerts first (`./nx delete` on your command, or by hand).

| Goal | Command |
|---|---|
| Load one phase of a sample into `samples/<CASE>/` (sends nothing) | `./nx phase AMF-001 AMF-002 AMF-003 AMF-004 AMF-006 --phase manifest` |
| Phase 2: House(s) first, then Master | `./nx phase AMF-001 ... AMF-006 --phase house-master` |
| Phase 3: Master, House(s), Manifest, Invoice, Packing List, Certificate of Origin | `./nx phase AMF-001 ... AMF-006 --phase master-house` |
| Preview what would be sent | `./run_regression.sh AMF-001 AMF-002 ... --dry-run` |
| Send the loaded phase (30 s between cases; AMF-005 has no Manifest, so it is not in the manifest phase) | `python -m nexus_agent suite --cases AMF-001 AMF-002 AMF-003 AMF-004 AMF-006 --interval 30` |
| After the Manifest-only phase: check the Master draft and House draft numbers in the UI | `./nx validate-drafts --cases AMF-001 AMF-002 AMF-003 AMF-004 AMF-006` |

Samples: `samples/air manifest individual scenarios/` (the six consolidated PDFs) and its `split/<FJ>/` folders (individual documents). Expected Master/House numbers: `air_manifest_scenarios` in `config/settings.yaml`.
