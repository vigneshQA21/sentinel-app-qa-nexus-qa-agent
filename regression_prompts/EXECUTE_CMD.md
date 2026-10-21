# Execute commands (no Claude needed)

Always start from the project folder. `./nx` and `./run_regression.sh` always use the project's own Python, so they work
from any terminal. **Whatever you run is really sent** (a preview needs `--dry-run`).

```bash
cd /home/unifo/Downloads/nexus_agent
```

## Most used (the daily routine)
```bash
./run_regression.sh REG-001 --validate    # 1. THE full run: send -> wait for Nexus -> mapping check -> Master data check (all fields printed)
./nx validate-master                      # 2. Re-check the Master data of what is ALREADY in Nexus (no send). Defaults to REG-001
./nx validate                             # 3. Re-check the mapping (Master/House/Manifest/Invoice/Packing) of what is already in Nexus
./run_regression.sh REG-001               # 4. Send only, no UI check
./nx login                                # 5. Nexus session expired: log in by hand once (press Enter, or close the window)
```
**Before every run:** delete the old pre-alerts of that case in Nexus. Otherwise the new email is linked to the old
pre-alert and lands in *Others* as a duplicate. (Nothing is deleted automatically yet.)

## What `./run_regression.sh <CASE> --validate` does (time counted from sending, T)
| When | What |
|---|---|
| T+0:00 | the case's emails are sent (the Nexus login is checked first; if it expired, nothing is sent) |
| T+3:00 | buffer over: first look in Nexus (countdown printed meanwhile) |
| T+3:00 to T+7:00 | polls every 20 s until the pre-alert appears and its job progress is 100% |
| then | **mapping check** (which document sits under Master / House / Manifest) and **Master data check** (every field printed as `field : value` with the count, compared with the source PDF) |
| T+7:00 | still nothing in Nexus: the case is reported NOT_RECEIVED |

The browser is always visible. Several cases: each is sent, validated, then the next one is sent.
Timing is in `config/settings.yaml` -> `validation:` (`initial_wait_seconds`, `poll_seconds`, `max_wait_seconds`).

## Several cases / the daily tag AIR_SINGLE_HOUSE_DAILY (15 emails)
```bash
./run_regression.sh REG-001 REG-002 --validate     # per case: send -> validate -> next
./run_regression.sh air-daily --validate           # REG-001, 002, 005, 009 (+ 006, 007 sent, UI validation for them not built yet)
./run_regression.sh air-daily                      # send only, 5-minute gap between cases
```
Cases with samples: REG-001, 002, 005, 006, 007, 009. REG-003 is excluded (same shipment as REG-007); REG-011 and REG-016 have no sample.

## Where to look afterwards
| What | Where |
|---|---|
| Send report | `runs/_reports/suite_<time>.csv` |
| Mapping report | `runs/_reports/validate_<time>.csv` |
| Master data report (every field, expected vs Nexus) | `runs/_reports/master_data_<time>.csv` |
| Screenshots | `runs/<date>/<case>/` |
| What was sent | Gmail Sent, search `"Regression testing"` |

## Flags (`run_regression.sh`)
| Flag | Meaning |
|---|---|
| `--validate` | after each case is sent: buffer, polling, mapping check, Master data check |
| `--no-wait` | no 5-minute gap between cases (send only; `--validate` spaces cases itself) |
| `--no-force` | skip cases that fail screening (REG-002 and REG-009 would be skipped) |
| `--dry-run` | preview only, sends nothing |

`./nx validate` and `./nx validate-master` also take `--cases REG-002 ...`, `--wait <seconds>` and `--headless`.

## Occasionally
```bash
./nx cases                                   # list the cases and how many samples each has
./nx ingest                                  # file downloads from samples/_inbox/ under their case
.venv/bin/python scripts/check_session.py    # LOGGED IN / SESSION EXPIRED
.venv/bin/python -m pytest -q                # run the tests
```

## Good to know
- The Master data check treats the PDF in `samples/<CASE>/` as the source of truth. Verdicts: PASS, FAIL, INFO (data Nexus
  holds itself, e.g. Party ID, not on the document), NOT_VERIFIABLE (could not be read from the document).
- The check looks in Nexus's **Pre-Alerts** tab only. A duplicate in *Others* shows as NOT_RECEIVED.
- Same flow with Claude: say "Execute AIR_SINGLE_HOUSE_DAILY" (uses many more tokens; see `air/AIR_SINGLE_HOUSE_DAILY.md`).

_Last updated 2026-10-21: House, Manifest, Invoice and Packing List data checks are next._
