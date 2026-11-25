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
