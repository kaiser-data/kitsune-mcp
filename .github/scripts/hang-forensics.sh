#!/usr/bin/env bash
# Capture forensics for a wedged python process WITHOUT signalling it.
# The process is suspected to be in uninterruptible D-state sleep, so we only
# READ kernel state (/proc) and use py-spy --nonblocking (process_vm_readv,
# no ptrace attach — an attach would itself hang on a D-state task).
#
# Usage: hang-forensics.sh <logfile>
# Writes hang-forensics.txt and mirrors everything to stdout.
set +e
LOG="${1:-test.log}"
OUT="hang-forensics.txt"

# The wedged process was launched as: python -X importtime ...
PYPID=$(pgrep -f -- '-X importtime' | head -1)

{
  echo "===== hang forensics ====="
  echo "target pid: ${PYPID:-NOT FOUND}"

  echo
  echo "--- full process table (pid,ppid,pgid,sess,STAT,WCHAN,etime,args) ---"
  ps -eo pid,ppid,pgid,sess,stat,wchan:32,etime,args --sort=pid | tail -70

  if [ -n "$PYPID" ]; then
    echo
    echo "--- /proc/$PYPID/status ---"
    cat "/proc/$PYPID/status" 2>/dev/null
    echo
    echo "--- /proc/$PYPID/wchan ---"
    cat "/proc/$PYPID/wchan" 2>/dev/null
    echo
    echo
    echo "--- kernel stack of every thread (needs root) ---"
    for t in /proc/"$PYPID"/task/*/; do
      tid=$(basename "$t")
      comm=$(cat "${t}comm" 2>/dev/null)
      state=$(awk '{print $3}' "${t}stat" 2>/dev/null)
      echo "== tid $tid comm=$comm state=$state wchan=$(cat "${t}wchan" 2>/dev/null)"
      sudo cat "${t}stack" 2>/dev/null || echo "(stack unavailable)"
    done
    echo
    echo "--- open fds ---"
    sudo ls -l "/proc/$PYPID/fd" 2>/dev/null | head -50
    echo
    echo "--- direct children ---"
    ps --ppid "$PYPID" -o pid,stat,wchan:32,args 2>/dev/null
    echo
    echo "--- py-spy dump (nonblocking read of the Python stack) ---"
    pip install -q py-spy >/dev/null 2>&1
    sudo "$(command -v py-spy)" dump --nonblocking --pid "$PYPID" 2>&1
  fi

  echo
  echo "--- last 40 importtime lines from $LOG ---"
  grep 'import time:' "$LOG" 2>/dev/null | tail -40 || echo "(none)"
  echo
  echo "--- tail of $LOG ---"
  tail -120 "$LOG" 2>/dev/null || echo "(no log)"
} 2>&1 | tee "$OUT"

exit 0
