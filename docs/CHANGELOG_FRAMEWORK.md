# Framework hardening change log

One entry per stage of the approved plan (audit doc, 25 Nov 2026). Branch: `framework-hardening`.
Full rollback at any time: `git checkout baseline-2026-11-25`. India stays in today's `config/`, `state/` and `runs/` folders.

## Gates
- **Offline gate** (every stage): `.venv/bin/python -m pytest -q` must stay at >= 177 passed, 0 failed, 0 skipped.
- **Live Golden gate** (stages that touch Nexus behaviour, only with authorisation): run the Golden cases, compare with
  `runs/golden/` (frozen 25 Nov 2026, see `runs/golden/manifest.json`). A field that was MATCH/PASS in the baseline and is
  anything else now blocks the stage. Environment failures (NOT_RECEIVED, session, timeout) are reported apart and re-run.

## Stage 0 - Safeguard (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `.gitignore` (new), `requirements.lock.txt` (new), `README.md` (install line), this file (new); `runs/golden/` (local only, not in git) |
| Reason | Audit C1, M7, M8: reproducible start, stop committing customer data, pinned versions |
| Baseline commit | `308aa41`, tag `baseline-2026-11-25`: the checker fixes of 20-23 Nov (select_parent wait, read_parents retry, loader-aware clicks, AMF ids in delete, live page on start) |
| Existing behaviour affected | None: no code changed in this stage |
| `.gitignore` | Ignores `.env`, `secrets/`, `state/`, `.venv/`, caches, `runs/`, `samples/`, `knowledge_base/`. Files already tracked stay tracked (history untouched); removing them from the repo is a separate decision |
| Golden baseline | `runs/golden/2026-11-20/` (21 cases) and `runs/golden/2026-11-19/` (REG-001, SEA-REG-002): 30 files, read-only, SHA-256 in `manifest.json` |
| Database | Backup `state/backup/agent_20261125_stage0.db`; schema unchanged |
| Tests | Offline gate: see the stage 0 commit message |
| Rollback | `git revert <stage 0 commit>`; `runs/golden/` can be deleted, nothing reads it yet |

## Stage 1 - Config check and start-up banner (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/config.py` (`ConfigError`, `REQUIRED_SETTINGS`, `REQUIRED_UAT_SELECTORS`, `Config.config_dir`, `.tenant`, `.problems()`, `.validate()`, `.banner()`), `nexus_agent/__main__.py` (validate + banner right after the config is built), `tests/test_config.py` (new, 6 tests), `README.md` |
| Reason | Audit H5: a missing key failed mid-run with a KeyError; nothing showed which tenant, Nexus, database or runs folder a run used |
| Existing behaviour affected | None for a valid config. The banner goes to **stderr**, so stdout is unchanged: `cases` (18 lines), `bugs --list` (1,347 lines) and `history` (1,206 lines) were byte-identical to the baseline tag. `Config()` used directly (tests, modules) does not validate, as before |
| New behaviour | Every `./nx` command prints `[nexus-agent] tenant=... profile=... nexus=... config=... db=... runs=...` on stderr; a broken config stops with exit 2 and lists every problem at once. `tenant` defaults to `india` when settings has no `tenant:` key (India's settings.yaml is not changed) |
| Tests | Offline gate: see the stage 1 commit message. Live Golden gate: not needed (no Nexus behaviour changed) |
| Rollback | `git revert <stage 1 commit>` |

## Stage 2 - Tenant layout (2026-11-25)
| Item | Detail |
| --- | --- |
| Files | `nexus_agent/config.py` (`DEFAULT_TENANT`, `available_tenants`, `tenant_config_dir`, `Config(tenant=...)`, isolation checks), `nexus_agent/__main__.py` (`--tenant`), `run_regression.sh` (`--tenant`, log folder and recipient from the tenant's config), `nexus_agent/casedoc.py` (workbook folder from settings), `tests/test_tenant_isolation.py` (new, 10 tests), `regression_prompts/EXECUTE_CMD.md` |
| Reason | Audit H1: one database, session and runs folder for everything |
| Layout | India (default, or `--tenant india`): today's `config/`, `state/`, `runs/`, nothing moved. Any other tenant: `config/<name>/` with `tenant: <name>`; its `state_dir`, `runs_dir` and `session_file` must sit in a `<name>` folder, else the run stops. `--tenant` and `--config` together are refused. No Dubai or Japan config is created in this stage |
| Shared on purpose | `state/ocr_cache` (keyed by the page image itself, holds no tenant result), `secrets/` OAuth client (each tenant names its own token files in settings) |
| Existing behaviour affected | None for India: `./nx --tenant india cases` = `./nx cases` (stdout identical); `run_regression.sh` dry-run of all 23 cases lists the same 32 emails as the 23 Nov 2026 dry-run, logs still go to `runs/_logs`, the "SENDING to ..." line names the same mailbox (now read from config). A dry-run still ends with exit 1, as before |
| Tests | Offline gate: see the stage 2 commit message. Live Golden gate: pending your authorisation |
| Rollback | `git revert <stage 2 commit>` |
