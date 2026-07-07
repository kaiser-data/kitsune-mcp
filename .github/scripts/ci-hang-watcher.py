#!/usr/bin/env python3
"""Pre-armed, fork-free hang watcher for the Linux CI test hang (PR #49).

Every post-mortem capture so far died because the wedge poisons process
creation machine-wide: after pytest wedges, ANY fork on the runner blocks
uninterruptibly (pgrep, sleep, probe launches, the runner's own teardown).
So this watcher is started BEFORE pytest (as root, detached) and after the
wedge does strictly fork-free work:

  - hang detection : os.stat() on test.log (frozen size + no exit file)
  - kernel stacks  : SysRq-W via a PRE-OPENED fd to /proc/sysrq-trigger,
                     read back via a PRE-OPENED non-blocking fd to /dev/kmsg
  - exfiltration   : PR comment via urllib HTTPS (sockets don't fork) —
                     immune to step/job cancellation and log retention

Never touches /proc/<wedged-pid>/* — those reads block on the wedged task.

Usage: ci-hang-watcher.py <test-log> <exit-file> <repo> <pr-number> <label>
Env:   GH_TOKEN (posting skipped if empty), WATCH_SECONDS (default 480)
"""
import json
import os
import sys
import time
import urllib.request

LOG, EXIT_FILE, REPO, PR, LABEL = sys.argv[1:6]
WATCH_SECONDS = int(os.environ.get("WATCH_SECONDS", "480"))
FREEZE_SECONDS = 90
TOKEN = os.environ.get("GH_TOKEN", "")

def note(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

# --- pre-arm everything that must not fork/open later -----------------------
try:
    kmsg = os.open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
except OSError as e:
    kmsg = -1
    note("kmsg unavailable:", e)
try:
    sysrq = os.open("/proc/sysrq-trigger", os.O_WRONLY)
except OSError as e:
    sysrq = -1
    note("sysrq unavailable:", e)

def drain_kmsg():
    out = []
    if kmsg < 0:
        return out
    while True:
        try:
            rec = os.read(kmsg, 8192)
        except BlockingIOError:
            break
        except OSError:  # EPIPE on ring-buffer overrun — keep reading
            continue
        if not rec:
            break
        out.append(rec.decode(errors="replace"))
    return out

def post_comment(body):
    if not (TOKEN and PR):
        note("no token/PR — skipping post")
        return
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues/{PR}/comments",
        data=json.dumps({"body": body}).encode(),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            note("posted comment:", r.status)
    except Exception as e:
        note("post failed:", e)

def tail_of(path, n=6000):
    try:
        with open(path, errors="replace") as f:
            return f.read()[-n:]
    except OSError as e:
        return f"(cannot read {path}: {e})"

# --- watch loop: fork-free ---------------------------------------------------
drain_kmsg()  # discard boot-time backlog so later reads are wedge-era only
start = time.time()
last_size, last_change = -1, time.time()
hang = False
while time.time() - start < WATCH_SECONDS:
    if os.path.exists(EXIT_FILE):
        note("pytest exited cleanly — watcher done")
        sys.exit(0)
    try:
        size = os.stat(LOG).st_size
    except OSError:
        size = -1
    if size != last_size:
        last_size, last_change = size, time.time()
    elif size >= 0 and time.time() - last_change > FREEZE_SECONDS:
        hang = True
        break
    time.sleep(5)

if not hang:
    note("watch window ended without a frozen log; treating as hang anyway")

note(f"HANG: {LOG} frozen at {last_size}B for {int(time.time() - last_change)}s")

# Kernel stacks of ALL blocked (D-state) tasks, via the pre-opened fds.
if sysrq >= 0:
    try:
        os.write(sysrq, b"w")
        note("triggered SysRq-W")
    except OSError as e:
        note("sysrq write failed:", e)
time.sleep(10)
kernel = "".join(drain_kmsg())

body = f"""## 🔍 CI hang forensics — `{LABEL}` (posted live by the pre-armed watcher)

`{LOG}` frozen at **{last_size}** bytes for {FREEZE_SECONDS}s+, no exit file after {int(time.time() - start)}s.

### tail of {LOG} (the last test that started never finished)
```
{tail_of(LOG)}
```

### SysRq-W — kernel stacks of all uninterruptible (D-state) tasks
```
{kernel[-45000:] if kernel.strip() else "(no kmsg output captured)"}
```
"""
try:
    with open(f"hang-report-{LABEL}.md", "w") as f:
        f.write(body)
except OSError:
    pass
post_comment(body)
note("watcher done (hang path)")
sys.exit(1)
