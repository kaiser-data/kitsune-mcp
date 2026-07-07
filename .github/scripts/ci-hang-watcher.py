#!/usr/bin/env python3
"""Flight-recorder watcher for the Linux CI hang (PR #49).

Evidence so far: the previous watcher's heartbeat froze at t+0s on BOTH
matrix jobs — within 30s of pytest starting, even a root process doing only
stat()+HTTPS could no longer edit a PR comment, and test.log was still pure
importtime output. The box dies during pytest collection/startup, fast and
machine-wide (memory thrash and fork storm are the prime suspects).

So v4 is a flight recorder: every ~8s it PATCHes a PR comment with system
vitals (MemAvailable, swap, loadavg, task count from /proc/loadavg — no
forks), freeze age, the collected log tail, and recent kmsg lines. Every
network call runs in a fire-and-forget daemon thread so the main loop can
never block on the API. When the box dies, the last successful edit shows
exactly what the vitals were doing on the way down. On freeze it also fires
SysRq-W (D-state kernel stacks) + SysRq-M (memory report) via pre-opened fds.

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
FREEZE_SECONDS = 6
BEAT_SECONDS = 4
try:
    TOKEN = open(os.environ.get("GH_TOKEN_FILE", ".ghtoken")).read().strip()
except OSError:
    TOKEN = ""

def note(*a):
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

def api(method, path, body=None, timeout=20):
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
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or "{}")
    except Exception as e:
        note(f"api {method} {path} failed:", e)
        return None

note("armed — token:", "present" if TOKEN else "MISSING", "| pr:", PR or "(none)")

# --- pre-armed fds ------------------------------------------------------------
def _pre_open(path, flags):
    try:
        return os.open(path, flags)
    except OSError as e:
        note(path, "unavailable:", e)
        return -1

kmsg = _pre_open("/dev/kmsg", os.O_RDONLY | os.O_NONBLOCK)
sysrq = _pre_open("/proc/sysrq-trigger", os.O_WRONLY)
meminfo_fd = _pre_open("/proc/meminfo", os.O_RDONLY)
loadavg_fd = _pre_open("/proc/loadavg", os.O_RDONLY)
psi_io_fd = _pre_open("/proc/pressure/io", os.O_RDONLY)
psi_mem_fd = _pre_open("/proc/pressure/memory", os.O_RDONLY)

def read_fd(fd, n=4096):
    if fd < 0:
        return ""
    try:
        os.lseek(fd, 0, 0)
        return os.read(fd, n).decode(errors="replace")
    except OSError as e:
        return f"(read failed: {e})"

def vitals():
    mem = {}
    for line in read_fd(meminfo_fd).splitlines():
        k = line.split(":")[0]
        if k in ("MemTotal", "MemAvailable", "MemFree", "SwapTotal", "SwapFree", "Committed_AS"):
            mem[k] = line.split()[1]  # kB
    psi = " ".join(
        f"psi_{n}={read_fd(fd).splitlines()[0].split()[1] if read_fd(fd) else '?'}"
        for n, fd in (("io", psi_io_fd), ("mem", psi_mem_fd)))
    return f"loadavg={read_fd(loadavg_fd).strip()} | {psi} | " + \
           " ".join(f"{k}={int(v)//1024}M" for k, v in mem.items())

# --- kmsg ring (drained continuously; keep last ~200 lines) --------------------
kmsg_ring: list = []

def drain_kmsg():
    while kmsg >= 0:
        try:
            rec = os.read(kmsg, 8192)
        except BlockingIOError:
            return
        except OSError:
            continue
        if not rec:
            return
        kmsg_ring.append(rec.decode(errors="replace"))
        del kmsg_ring[:-200]

drain_kmsg()
kmsg_ring.clear()  # discard boot backlog

# --- disposable tail thread (only reader of test.log) --------------------------
tail_buf: list = []
tail_lock = threading.Lock()

def _tailer():
    f = None
    while f is None:
        try:
            f = open(LOG, "rb")
        except OSError:
            time.sleep(0.5)
    while True:
        try:
            chunk = f.read()  # may block forever post-wedge — expendable
        except OSError:
            return
        if chunk:
            with tail_lock:
                tail_buf.append(chunk)
                while sum(len(c) for c in tail_buf) > 65536:
                    tail_buf.pop(0)
        else:
            time.sleep(1)

threading.Thread(target=_tailer, daemon=True).start()

def collected_tail(n):
    with tail_lock:
        data = b"".join(tail_buf)
    return data[-n:].decode(errors="replace") or "(nothing collected yet)"

# --- heartbeat: every network call is fire-and-forget --------------------------
hb = api("POST", f"/issues/{PR}/comments",
         {"body": f"🫀 flight recorder `{LABEL}` armed"})
hb_id = hb.get("id") if hb else None
note("heartbeat comment id:", hb_id)
beats: list = []  # rolling status lines, newest last

def _patch(body):
    api("PATCH", f"/issues/comments/{hb_id}", {"body": body})

def heartbeat(status):
    if not hb_id:
        return
    beats.append(status)
    del beats[:-15]
    body = (f"🫀 flight recorder `{LABEL}` — newest last, each line ~{BEAT_SECONDS}s apart\n\n"
            f"```\n" + "\n".join(beats) + "\n```\n"
            f"<details><summary>collected test.log tail</summary>\n\n"
            f"```\n{collected_tail(2500)}\n```\n</details>\n"
            f"<details><summary>recent kmsg</summary>\n\n"
            f"```\n{''.join(kmsg_ring)[-2500:] or '(quiet)'}\n```\n</details>")
    threading.Thread(target=_patch, args=(body,), daemon=True).start()

# --- main loop: stat + pre-opened fds only --------------------------------------
start = time.time()
last_size, last_change = -1, time.time()
last_beat = 0.0
frozen = False
while time.time() - start < WATCH_SECONDS:
    if os.path.exists(EXIT_FILE):
        note("pytest exited cleanly")
        heartbeat(f"t+{int(time.time()-start)}s CLEAN EXIT — suite finished")
        time.sleep(5)
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
    drain_kmsg()
    if time.time() - last_beat >= BEAT_SECONDS:
        last_beat = time.time()
        heartbeat(f"t+{int(time.time()-start):>3}s log={last_size}B "
                  f"frozen={int(time.time()-last_change)}s | {vitals()}")
    time.sleep(2)

state = "FROZEN" if frozen else "WATCH WINDOW EXPIRED"
note(f"{state}: {LOG} at {last_size}B for {int(time.time() - last_change)}s")
# The VM dies ~8-12s after the log freezes — fire SysRq-W NOW, post NOW.
if sysrq >= 0:
    try:
        os.write(sysrq, b"w")
    except OSError as e:
        note("sysrq w failed:", e)
time.sleep(3)
drain_kmsg()
kernel = "".join(kmsg_ring)

body = f"""## 🔍 CI hang forensics — `{LABEL}`

`{LOG}` {state.lower()}: **{last_size}** bytes, unchanged {int(time.time() - last_change)}s, \
{int(time.time() - start)}s after pytest launch.
Final vitals: {vitals()}

### tail of {LOG}, collected pre-wedge
```
{collected_tail(6000)}
```

### SysRq-W (D-state stacks) + SysRq-M (memory)
```
{kernel[-42000:] if kernel.strip() else "(no kmsg output captured)"}
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
