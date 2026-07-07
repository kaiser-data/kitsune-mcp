#!/usr/bin/env bash
# Capture forensics for a wedged python process WITHOUT wedging ourselves.
#
# Lesson from run 28849962924: the wedged process blocks readers of its
# /proc/<pid>/cmdline (and anything else needing its mmap_sem) — pgrep -f and
# `ps -o args` both wedged the forensics step itself in D-state, which then
# blocked step teardown and killed the whole job. So here:
#   - The target pid is read from a FILE (pytest.pid) — never pgrep.
#   - Every read that may need target-side locks (status, cmdline, py-spy)
#     runs in its OWN detached session (setsid -f) with a grace period; we
#     read whatever output files appeared and never wait on the readers.
#   - Inline reads are limited to provably lock-free sources: plain files,
#     dmesg, /proc/<pid>/wchan, task stacks, comm, stat.
#
# Usage: hang-forensics.sh <logfile> <pidfile>
set +e
LOG="${1:-test.log}"
PIDFILE="${2:-pytest.pid}"
OUT="hang-forensics.txt"
D=forensic-probes
mkdir -p "$D"

PYPID=$(cat "$PIDFILE" 2>/dev/null)

# ---- launch risky probes detached; never wait on them -----------------------
if [ -n "$PYPID" ]; then
  setsid -f bash -c "cat /proc/$PYPID/status  > $D/status.txt  2>&1" || true
  setsid -f bash -c "tr '\0' ' ' < /proc/$PYPID/cmdline > $D/cmdline.txt 2>&1" || true
  setsid -f bash -c "sudo ls -l /proc/$PYPID/fd > $D/fds.txt 2>&1" || true
  setsid -f bash -c "pip install -q py-spy && sudo \$(command -v py-spy) dump --nonblocking --pid $PYPID > $D/pyspy.txt 2>&1" || true
fi

{
  echo "===== hang forensics (v2: lock-safe) ====="
  echo "target pid: ${PYPID:-NOT FOUND}"

  echo
  echo "--- tail of $LOG (how far did pytest get?) ---"
  tail -150 "$LOG" 2>/dev/null || echo "(no log)"

  echo
  echo "--- last 40 importtime lines ---"
  grep 'import time:' "$LOG" 2>/dev/null | tail -40 || echo "(none)"

  echo
  echo "--- kernel hung-task reports (dmesg) ---"
  sudo dmesg 2>/dev/null | grep -iE 'hung|blocked for more|stuck' -A 25 | tail -120 || echo "(none)"

  if [ -n "$PYPID" ]; then
    echo
    echo "--- /proc/$PYPID/wchan ---"
    cat "/proc/$PYPID/wchan" 2>/dev/null; echo
    echo
    echo "--- /proc/$PYPID/stat (field 3 = state) ---"
    cat "/proc/$PYPID/stat" 2>/dev/null
    echo
    echo "--- every thread: comm/state/wchan + kernel stack ---"
    for t in /proc/"$PYPID"/task/*/; do
      tid=$(basename "$t")
      echo "== tid $tid comm=$(cat "${t}comm" 2>/dev/null) wchan=$(cat "${t}wchan" 2>/dev/null)"
      sudo cat "${t}stack" 2>/dev/null || echo "(stack unavailable)"
    done
    echo
    echo "--- descendant pids (via /proc children — lock-free) ---"
    for c in $(cat /proc/"$PYPID"/task/*/children 2>/dev/null); do
      echo "== child $c comm=$(cat /proc/$c/comm 2>/dev/null) wchan=$(cat /proc/$c/wchan 2>/dev/null) stat=$(awk '{print $3}' /proc/$c/stat 2>/dev/null)"
      sudo cat "/proc/$c/stack" 2>/dev/null || true
      # grandchildren too
      for g in $(cat /proc/"$c"/task/*/children 2>/dev/null); do
        echo "==== grandchild $g comm=$(cat /proc/$g/comm 2>/dev/null) wchan=$(cat /proc/$g/wchan 2>/dev/null) stat=$(awk '{print $3}' /proc/$g/stat 2>/dev/null)"
        sudo cat "/proc/$g/stack" 2>/dev/null || true
      done
    done
  fi

  echo
  echo "--- waiting 20s for detached probes (status/cmdline/fds/py-spy) ---"
  sleep 20
  for f in status cmdline fds pyspy; do
    echo "== probe: $f"
    cat "$D/$f.txt" 2>/dev/null || echo "(probe did not return — that read blocks on the wedged task)"
  done
} 2>&1 | tee "$OUT"

exit 0
