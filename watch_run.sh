#!/usr/bin/env bash
# Follows the regression output live in this terminal (e.g. the VS Code terminal). It tails the newest log in runs/_logs/ and
# switches by itself when a newer run starts. Stop with Ctrl+C. Shows what the agent does: screening, sends, waits, checks, results.
#   ./watch_run.sh            newest log
#   ./watch_run.sh reg002     the newest log whose name contains "reg002"
cd "$(dirname "$0")" || exit 1
pick() { ls -t runs/_logs/*${1}*.log 2>/dev/null | head -1; }
cur=""; pid=""
trap '[ -n "$pid" ] && kill $pid 2>/dev/null; exit 0' INT TERM
while true; do
  n=$(pick "$1")
  if [ -n "$n" ] && [ "$n" != "$cur" ]; then
    [ -n "$pid" ] && kill $pid 2>/dev/null
    cur="$n"; echo; echo "===== following $cur  ($(date +%H:%M:%S)) ====="
    tail -n 25 -F "$cur" 2>/dev/null | grep --line-buffered -v -e fontTools -e "INFO nexus_agent.nexus.session" &
    pid=$!
  fi
  sleep 3
done
