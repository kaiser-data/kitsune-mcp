"""A wrapper that exited can leave its server running in its process group (review 2: Codex #12).

Kitsune spawns every child as a session leader, so the group id is the
wrapper's pid. POSIX never reuses a pid while a process group with that id
exists, so: no process holds the pid but the group exists → the group is ours.
"""

import asyncio
import os
import signal
import sys
from unittest.mock import MagicMock

import pytest

import kitsune_mcp.transport as tp

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


async def test_surviving_child_of_an_exited_wrapper_is_killed():
    p = await asyncio.create_subprocess_exec(
        "sh", "-c", "sleep 60 & exit 0", start_new_session=True
    )
    await p.wait()
    try:
        assert _group_alive(p.pid), "test setup: the sleep should outlive its wrapper"
        tp._kill_process_tree(p)
        for _ in range(50):
            if not _group_alive(p.pid):
                break
            await asyncio.sleep(0.02)
        assert not _group_alive(p.pid)
    finally:
        if _group_alive(p.pid):
            os.killpg(p.pid, signal.SIGKILL)


def test_reused_pid_is_left_alone(monkeypatch):
    """A live process holds the pid: it may be a stranger's new group. Never killpg it."""
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.returncode = 0
    proc.pid = 424242
    killpg = MagicMock()
    monkeypatch.setattr(tp.os, "kill", lambda pid, sig: None)  # "a process has this pid"
    monkeypatch.setattr(tp.os, "killpg", killpg)
    tp._kill_process_tree(proc)
    killpg.assert_not_called()


def test_mock_processes_never_reach_killpg(monkeypatch):
    """Tests use MagicMock procs with fake pids; the orphan path must ignore them."""
    proc = MagicMock()
    proc.returncode = 1
    proc.pid = 99999
    killpg = MagicMock()
    monkeypatch.setattr(tp.os, "killpg", killpg)
    tp._kill_process_tree(proc)
    killpg.assert_not_called()
