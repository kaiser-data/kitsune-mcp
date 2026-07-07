#!/usr/bin/env bash
# Run pytest with a watchdog, fully detached from the CI step (launch me via
# `setsid`). On hang, trigger lock-safe forensics. The CI step must only poll
# for the plain files this writes: pytest.exit OR forensics.done.
set +e

PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 \
  python -X importtime -m pytest tests/ -v --tb=short \
  --cov=kitsune_mcp --cov-report=xml > test.log 2>&1 &
P=$!
echo "$P" > pytest.pid

# Healthy suite: ~15s. 300s lets pytest-timeout (60s/test), faulthandler (90s)
# and the kernel hung-task detector (120s) all fire first if they can.
for _ in $(seq 1 300); do
  kill -0 "$P" 2>/dev/null || break
  sleep 1
done

if kill -0 "$P" 2>/dev/null; then
  bash "$(dirname "$0")/hang-forensics.sh" test.log pytest.pid
  touch forensics.done
else
  wait "$P"
  echo $? > pytest.exit
fi
