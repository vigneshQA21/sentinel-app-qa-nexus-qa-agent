#!/usr/bin/env bash
# Run regression cases without Claude. EXECUTES (sends) by default.
#   ./run_regression.sh REG-001                 -> sends REG-001
#   ./run_regression.sh REG-006 REG-007         -> sends both (5 min gap between cases)
#   ./run_regression.sh air-daily               -> sends the whole AIR_SINGLE_HOUSE_DAILY set
# Tenant: --tenant <name> (default india: today's config/, state/, runs/); every command of the run uses that tenant only.
# Flags: --validate (after EACH case is sent: wait 3 min buffer, poll until Nexus shows it, validate the mapping; headed)  --dry-run (preview only, sends nothing)  --no-wait (no 5-minute gap)  --no-force (skip cases that fail screening)
export PYTHONUNBUFFERED=1   # show output immediately, even through a pipe
cd "$(dirname "$0")" && source .venv/bin/activate || exit 1
cases=(); dry=(); force=(--force); wait=(); validate=0; tenant=()
while [ $# -gt 0 ]; do
  a="$1"; shift
  case "$a" in
    --tenant) [ $# -gt 0 ] || { echo "--tenant needs a name"; exit 2; }; tenant=(--tenant "$1"); shift ;;
    --tenant=*) tenant=(--tenant "${a#--tenant=}") ;;
    air-daily) cases+=(REG-001 REG-002 REG-005 REG-009 REG-006 REG-007) ;;
    sea-daily) cases+=(SEA-REG-001 SEA-REG-002 SEA-REG-003 SEA-REG-004 SEA-REG-005 SEA-REG-006 SEA-REG-007 SEA-REG-008 SEA-REG-009) ;;
    --dry-run) dry=(--dry-run) ;;
    --validate) validate=1 ;;
    --no-wait) wait=(--interval 0) ;;
    --no-force) force=() ;;
    REG-*|SEA-REG-*|AMF-*|MH-*|SEA-MH-*|SEA-RT-*|DBL-*|UNR-*) cases+=("$a") ;;
    *) echo "unknown argument: $a"; exit 2 ;;
  esac
done
[ ${#cases[@]} -eq 0 ] && { sed -n '2,8p' "$0"; exit 2; }
# The tenant's own log folder and mailbox come from its configuration (India: runs/_logs, the forward_to of config/settings.yaml).
info=$(python - "${tenant[1]:-}" <<'PY'
import sys
from nexus_agent.config import Config, ConfigError
try:
    cfg = Config(tenant=sys.argv[1] or None)
    cfg.validate()
except ConfigError as exc:
    print(f"ERROR\t{exc}"); sys.exit(0)
print(f"{cfg.runs_dir / '_logs'}\t{cfg.settings['gmail']['forward_to']}")
PY
)
IFS=$'\t' read -r logdir recipient <<< "$info"
[ "$logdir" = "ERROR" ] && { echo "Nothing was run. $recipient"; exit 2; }
if [ ${#dry[@]} -eq 1 ]; then echo "DRY-RUN (nothing is sent): ${cases[*]}"
else echo "SENDING to $recipient: ${cases[*]}  (old pre-alerts must be deleted in Nexus first)"; fi
val=(); [ $validate -eq 1 ] && val=(--validate)      # validate right after each case is sent (headed browser, buffer + polling)
mkdir -p "$logdir"
python -m nexus_agent "${tenant[@]}" suite "${dry[@]}" "${force[@]}" "${wait[@]}" "${val[@]}" --cases "${cases[@]}" 2>&1 | grep --line-buffered -v -e fontTools -e "INFO nexus_agent.nexus.session" | tee -a "$logdir/run_$(date +%Y%m%d_%H%M%S).log"
[ ${#dry[@]} -eq 0 ] && python -m nexus_agent "${tenant[@]}" runreport 2>&1 | grep --line-buffered -v -e fontTools -e "INFO nexus_agent" | tee -a "$logdir/run_$(date +%Y%m%d_%H%M%S).log"   # observations, bugs and passed bugs of this run
[ ${#dry[@]} -eq 0 ] && python -m nexus_agent "${tenant[@]}" upload-evidence 2>&1 | grep --line-buffered -v -e fontTools | tee -a "$logdir/run_$(date +%Y%m%d_%H%M%S).log"   # screenshots + report PDF of the day to the Drive evidence folder
