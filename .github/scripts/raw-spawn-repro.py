#!/usr/bin/env python3
"""Kitsune-free control probes for the CI VM-kill.

Round-7 control froze at "spawn yes (unread PIPE) -> killpg(SIGKILL) -> wait".
This version runs ONE isolated raw-asyncio pattern per invocation (argv[1]),
so a matrix can pin the exact syscall sequence that wedges the runner.
No project imports.
"""
import asyncio
import os
import signal
import sys

CASE = sys.argv[1] if len(sys.argv) > 1 else "all"


def log(m):
    print(m, flush=True)


async def c_yes_pipe_kill():
    """yes -> unread PIPE (fills, child blocks in write) -> killpg -> wait."""
    log("spawn yes, PIPE unread, sleep, killpg SIGKILL, wait")
    p = await asyncio.create_subprocess_exec(
        "yes", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)
    await asyncio.sleep(0.5)
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    await p.wait()
    log("ok")


async def c_yes_pipe_drain_kill():
    """Same but drain stdout concurrently so the child never blocks."""
    log("spawn yes, drain PIPE, killpg, wait")
    p = await asyncio.create_subprocess_exec(
        "yes", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)

    async def drain():
        try:
            while await p.stdout.read(65536):
                pass
        except Exception:
            pass
    t = asyncio.ensure_future(drain())
    await asyncio.sleep(0.5)
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    await p.wait()
    t.cancel()
    log("ok")


async def c_yes_devnull_kill():
    """yes -> /dev/null (never blocks) -> killpg -> wait."""
    log("spawn yes -> DEVNULL, killpg, wait")
    p = await asyncio.create_subprocess_exec(
        "yes", stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True)
    await asyncio.sleep(0.5)
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    await p.wait()
    log("ok")


async def c_sleep_killpg():
    """sleep child -> killpg (no flood, isolates killpg itself)."""
    log("spawn sleep, killpg, wait")
    p = await asyncio.create_subprocess_exec(
        "sleep", "30", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True)
    await asyncio.sleep(0.2)
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    await p.wait()
    log("ok")


async def c_rapid_kill():
    """20 rapid sleep spawn/kill cycles, inherited stderr."""
    log("20x spawn sleep -> kill -> wait")
    for _ in range(20):
        p = await asyncio.create_subprocess_exec(
            "sleep", "10", stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=None, start_new_session=True)
        p.kill()
        await p.wait()
    log("ok")


CASES = {
    "yes-pipe-kill": c_yes_pipe_kill,
    "yes-pipe-drain-kill": c_yes_pipe_drain_kill,
    "yes-devnull-kill": c_yes_devnull_kill,
    "sleep-killpg": c_sleep_killpg,
    "rapid-kill": c_rapid_kill,
}


async def main():
    if CASE == "all":
        for name, fn in CASES.items():
            log(f"== {name}")
            await fn()
    else:
        await CASES[CASE]()
    log("CONTROL COMPLETE — no wedge")


asyncio.run(main())
