# Regression prompts

Saved prompts for the Nexus E2E Regression QA Agent. Each prompt has a **tag**. Ask for it by tag,
for example: **"Execute AIR_SINGLE_HOUSE_DAILY"**. The agent opens the matching file and follows it.

Folders are by MOT (mode of transport): `air/`, `sea/`.

| Tag | MOT | Suite | File |
|---|---|---|---|
| `AIR_SINGLE_HOUSE_DAILY` | AIR | Air_Single_House_Daily_Regression | [air/AIR_SINGLE_HOUSE_DAILY.md](air/AIR_SINGLE_HOUSE_DAILY.md) |

**Run without Claude:** see [EXECUTE_CMD.md](EXECUTE_CMD.md) (`./run_regression.sh REG-006` and more).

Naming: `<MOT>_<SCOPE>_<FREQUENCY>`, upper case, for example `SEA_SINGLE_HOUSE_DAILY`.

Every prompt dry-runs first and sends only after an explicit "go". Keep secrets, `state/` and production
documents out of these files.
