#!/usr/bin/env bash
# Capture forensics for a wedged python process WITHOUT wedging the caller.
#
# Lessons from runs 28849962924 / 28851945281: virtually ANY /proc/<pid>/*
# read on the wedged task can block uninterruptibly (cmdline via mmap_sem for
# sure; even stat/wchan/task walks wedged the v2 inline reads). So v3 runs
# EVERY per-pid read in its own throwaway session (setsid -f) writing to a
# plain file, sleeps out a grace period, and assembles whatever came back.
# This script itself never opens /proc of the target inline.
#
# Usage: hang-forensics.sh <logfile> <pidfile>
set +e
LOG="${1:-test.log}"
PIDFILE="${2:-pytest.pid}"
OUT="hang-forensics.txt"
D=forensic-probes
mkdir -p "$D"

PYPID=$(cat "$PIDFILE" 2>/dev/null)
export PYPID

probe() {
  local name="$1" body="$2"
  printf '#!/usr/bin/env bash\nset +e\nPYPID=%s\n%s\n' "$PYPID" "$body" > "$D/$name.sh"
  setsid -f bash "$D/$name.sh" > "$D/$name.txt" 2>&1 || true
}

if [ -n "$PYPID" ]; then
  probe wchan   'cat /proc/$PYPID/wchan; echo'
  probe stat    'cat /proc/$PYPID/stat'
  probe status  'cat /proc/$PYPID/status'
  probe cmdline 'tr "\0" " " < /proc/$PYPID/cmdline'
  probe stacks  'for t in /proc/$PYPID/task/*/; do
    echo "== tid $(basename "$t") comm=$(cat "${t}comm" 2>/dev/null) state=$(awk "{print \$3}" "${t}stat" 2>/dev/null) wchan=$(cat "${t}wchan" 2>/dev/null)"
    sudo cat "${t}stack" 2>/dev/null || echo "(stack unavailable)"
  done'
  probe children 'for c in $(cat /proc/$PYPID/task/*/children 2>/dev/null); do
    echo "== child $c comm=$(cat /proc/$c/comm 2>/dev/null) state=$(awk "{print \$3}" /proc/$c/stat 2>/dev/null) wchan=$(cat /proc/$c/wchan 2>/dev/null)"
    sudo cat /proc/$c/stack 2>/dev/null
    for g in $(cat /proc/$c/task/*/children 2>/dev/null); do
      echo "==== grandchild $g comm=$(cat /proc/$g/comm 2>/dev/null) state=$(awk "{print \$3}" /proc/$g/stat 2>/dev/null) wchan=$(cat /proc/$g/wchan 2>/dev/null)"
      sudo cat /proc/$g/stack 2>/dev/null
    done
  done'
  probe fds   'sudo ls -l /proc/$PYPID/fd | head -60'
  probe pyspy 'pip install -q py-spy && sudo "$(command -v py-spy)" dump --nonblocking --pid "$PYPID"'
fi
probe dmesg 'sudo dmesg | tail -250'
probe pstable 'ps -eo pid,ppid,pgid,sess,stat,wchan:32,etime,comm | tail -80'

sleep 45

{
  echo "===== hang forensics (v3: fully detached probes) ====="
  echo "target pid: ${PYPID:-NOT FOUND}"
  echo
  echo "--- tail of $LOG (how far did pytest get?) ---"
  tail -150 "$LOG" 2>/dev/null || echo "(no log)"
  echo
  echo "--- last 40 importtime lines ---"
  grep 'import time:' "$LOG" 2>/dev/null | tail -40 || echo "(none)"
  for f in wchan stat status cmdline stacks children fds pyspy dmesg pstable; do
    echo
    echo "--- probe: $f ---"
    if [ -s "$D/$f.txt" ]; then
      cat "$D/$f.txt"
    else
      echo "(no output — this read blocks on the wedged task)"
    fi
  done
} > "$OUT" 2>&1

exit 0
