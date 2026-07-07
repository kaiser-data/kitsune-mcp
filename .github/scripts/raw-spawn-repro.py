#!/usr/bin/env python3
"""Kitsune-free control for the CI VM-kill bisection.

Mimics the raw process operations the killer test classes perform, with no
project imports at all. If this alone kills the runner, the trigger is real
asyncio subprocess spawning on ubuntu-latest, not project code.
"""
import asyncio
import sys


def log(msg):
    print(msg, flush=True)


async def main():
    log("1: spawn missing binary")
    try:
        await asyncio.create_subprocess_exec(
            "definitely_not_a_real_command_xyz",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        log(f"   ok: {e}")

    log("2: spawn echo, read, wait")
    p = await asyncio.create_subprocess_exec(
        "echo", "hello",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    out, _ = await p.communicate()
    log(f"   ok: {out!r}")

    log("3: spawn cat with big output + kill process group")
    import os
    import signal
    p = await asyncio.create_subprocess_exec(
        "yes",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    await asyncio.sleep(0.5)
    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
    await p.wait()
    log("   ok: killed group")

    log("4: 20 rapid spawn/kill cycles with inherited stderr")
    for i in range(20):
        p = await asyncio.create_subprocess_exec(
            "sleep", "10",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=None, start_new_session=True,
        )
        p.kill()
        await p.wait()
    log("   ok: 20 cycles")

    log("RAW REPRO COMPLETE — no kill triggered")
    return 0


sys.exit(asyncio.run(main()))
