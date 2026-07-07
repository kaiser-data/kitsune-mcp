#!/usr/bin/env python3
"""Pre-armed, self-evidencing hang watcher for the Linux CI test hang (PR #49).

The wedge poisons the runner VM progressively (reads of test.log block on the
wedged writer's i_rwsem; /proc/<pid> reads block on its mmap_sem; possibly
process spawning too) — so this watcher trusts NOTHING on the box after the
wedge and reports exclusively over HTTPS:

  - posts an "armed" PR comment at startup, then EDITS it every 30s as a
    heartbeat (elapsed, log size, freeze age, collected tail) — if the
    watcher itself ever wedges, the last heartbeat pinpoints where
  - tails test.log incrementally in a DISPOSABLE daemon thread while healthy
    (post-wedge reads block; only that thread is lost)
  - detects the freeze via os.stat() only
  - fires SysRq-W through a pre-opened fd (kernel stacks of all D-state tasks
    into the kmsg ring, read via a pre-opened non-blocking fd)
  - posts the final forensics as a NEW comment; deletes the heartbeat comment
    if the suite finishes cleanly

Usage: ci-hang-watcher.py <test-log> <exit-file> <repo> <pr-number> <label>
Env:   GH_TOKEN_FILE (path to token file), WATCH_SECONDS (default 480)
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
HEARTBEAT_SECONDS = 30
try:
    TOKEN = open(os.environ.get("GH_TOKEN_FILE", ".ghtoken")).read().strip()
except OSError:
    TOKEN = ""

def note(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

def api(method, path, body=None):
    if not (TOKEN and PR):
        return None
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or "{}")
    except Exception as e:
        note(f"api {method} {path} failed:", e)
        return None

note("armed — token:", "present" if TOKEN else "MISSING", "| pr:", PR or "(none)")

# --- pre-arm fds --------------------------------------------------------------
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

# --- disposable tail thread: the ONLY thing that ever reads test.log ---------
tail_buf: list = []
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

def collected_tail(n):
    with tail_lock:
        data = b"".join(tail_buf)
    return data[-n:].decode(errors="replace") or "(nothing collected yet)"

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

drain_kmsg()  # discard boot backlog

# --- heartbeat comment --------------------------------------------------------
hb = api("POST", f"/issues/{PR}/comments",
         {"body": f"🫀 hang watcher `{LABEL}` armed — heartbeats will edit this comment"})
hb_id = hb.get("id") if hb else None
note("heartbeat comment id:", hb_id)

def heartbeat(status):
    if hb_id:
        body = (f"🫀 hang watcher `{LABEL}` — {status}\n\n"
                f"<details><summary>collected test.log tail</summary>\n\n"
                f"```\n{collected_tail(3000)}\n```\n</details>")
        api("PATCH", f"/issues/comments/{hb_id}", {"body": body})

# --- watch loop ---------------------------------------------------------------
start = time.time()
last_size, last_change = -1, time.time()
last_beat = 0.0
frozen = False
while time.time() - start < WATCH_SECONDS:
    if os.path.exists(EXIT_FILE):
        note("pytest exited cleanly — removing heartbeat comment")
        if hb_id:
            api("DELETE", f"/issues/comments/{hb_id}")
        os._exit(0)
    try:
        size = os.stat(LOG).st_size
    except OSError:
        size = -1
    if size != last_size:
        last_size, last_change = size, time.time()
    elif size >= 0 and time.time() - last_change > FREEZE_SECONDS:
        frozen = True
        break
    if time.time() - last_beat >= HEARTBEAT_SECONDS:
        last_beat = time.time()
        heartbeat(f"t+{int(time.time()-start)}s, log={last_size}B, "
                  f"unchanged for {int(time.time()-last_change)}s")
    time.sleep(5)

state = "FROZEN" if frozen else "watch window expired without freeze"
note(f"HANG ({state}): {LOG} at {last_size}B for {int(time.time() - last_change)}s")
heartbeat(f"{state} at t+{int(time.time()-start)}s — firing SysRq-W")

if sysrq >= 0:
    try:
        os.write(sysrq, b"w")
        note("triggered SysRq-W")
    except OSError as e:
        note("sysrq write failed:", e)
time.sleep(10)
kernel = "".join(drain_kmsg())

body = f"""## 🔍 CI hang forensics — `{LABEL}`

`{LOG}` {state}: **{last_size}** bytes, unchanged {int(time.time() - last_change)}s, \
{int(time.time() - start)}s after pytest launch.

### tail of {LOG}, collected pre-wedge (the last test that started never finished)
```
{collected_tail(6000)}
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
api("POST", f"/issues/{PR}/comments", {"body": body})
note("watcher done (hang path)")
os._exit(1)
