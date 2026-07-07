#!/usr/bin/env python3
"""Pre-armed hang watcher for the Linux CI test hang (PR #49).

Root cause of every failed capture so far: pytest wedges MID-write() to
test.log — a page fault during the write needs mmap_sem (held by another
wedged thread), so the writer sleeps in D-state holding the file's i_rwsem.
From that moment, ANY read() of test.log (tail, cat, artifact upload) and any
/proc/<pid> access needing mmap_sem (cmdline, environ, py-spy) blocks
uninterruptibly too — including the runner's own teardown.

So this watcher, started BEFORE pytest as root and fully detached:
  - tails test.log incrementally in a DISPOSABLE daemon thread while the
    suite is healthy (post-wedge reads block — only that thread is lost)
  - detects the hang with os.stat() only (never blocks)
  - fires SysRq-W through a PRE-OPENED fd — kernel stacks of every D-state
    task land in the kmsg ring, read back via a pre-opened non-blocking fd
  - posts the last-started test + kernel stacks as a PR comment over HTTPS,
    immune to job cancellation, VM teardown, and step-log retention

Usage: ci-hang-watcher.py <test-log> <exit-file> <repo> <pr-number> <label>
Env:   GH_TOKEN (posting skipped if empty), WATCH_SECONDS (default 480)
"""
import json
import os
import sys
import threading
import time
import urllib.request

LOG, EXIT_FILE, REPO, PR, LABEL = sys.argv[1:6]
WATCH_SECONDS = int(os.environ.get("WATCH_SECONDS", "480"))
FREEZE_SECONDS = 90
TOKEN = os.environ.get("GH_TOKEN", "")

def note(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

note("armed — token:", "present" if TOKEN else "MISSING", "| pr:", PR or "(none)",
     "| watch:", WATCH_SECONDS, "s")

# --- pre-arm: everything opened before pytest can wedge ---------------------
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

# --- disposable tail thread: the ONLY thing that ever reads test.log --------
tail_buf: list = []          # chunks, capped to ~64KB total
tail_lock = threading.Lock()

def _tailer():
    f = None
    while f is None:
        try:
            f = open(LOG, "rb")
        except OSError:
            time.sleep(1)
    while True:
        try:
            chunk = f.read()  # may block forever once the writer wedges — expendable
        except OSError:
            return
        if chunk:
            with tail_lock:
                tail_buf.append(chunk)
                while sum(len(c) for c in tail_buf) > 65536:
                    tail_buf.pop(0)
        else:
            time.sleep(2)

threading.Thread(target=_tailer, daemon=True).start()

def collected_tail(n=6000):
    with tail_lock:
        data = b"".join(tail_buf)
    return data[-n:].decode(errors="replace") or "(nothing collected)"

def drain_kmsg():
    out = []
    if kmsg < 0:
        return out
    while True:
        try:
            rec = os.read(kmsg, 8192)
        except BlockingIOError:
            break
        except OSError:  # EPIPE on ring overrun — keep reading
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

# --- watch loop: main thread never opens test.log ----------------------------
drain_kmsg()  # discard boot backlog so later reads are wedge-era only
start = time.time()
last_size, last_change = -1, time.time()
while time.time() - start < WATCH_SECONDS:
    if os.path.exists(EXIT_FILE):
        note("pytest exited cleanly — watcher done")
        os._exit(0)
    try:
        size = os.stat(LOG).st_size
    except OSError:
        size = -1
    if size != last_size:
        last_size, last_change = size, time.time()
    elif size >= 0 and time.time() - last_change > FREEZE_SECONDS:
        break
    time.sleep(5)

note(f"HANG: {LOG} frozen at {last_size}B for {int(time.time() - last_change)}s")

if sysrq >= 0:
    try:
        os.write(sysrq, b"w")
        note("triggered SysRq-W")
    except OSError as e:
        note("sysrq write failed:", e)
time.sleep(10)
kernel = "".join(drain_kmsg())

body = f"""## 🔍 CI hang forensics — `{LABEL}` (posted live by the pre-armed watcher)

`{LOG}` frozen at **{last_size}** bytes for {FREEZE_SECONDS}s+ ({int(time.time() - start)}s into the run).

### tail of {LOG}, collected pre-wedge (the last test that started never finished)
```
{collected_tail()}
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
os._exit(1)
