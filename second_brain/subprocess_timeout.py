"""
subprocess_timeout.py - real, guaranteed termination for an external
subprocess a connector shells out to.

Not currently used by either shipped connector (capture, x_bookmarks are
both plain in-process Python) - this exists for the connector shape this
project explicitly documents but doesn't ship code for: one that runs an
external agent/CLI process per sync step (see docs/connector-contract.md).
That shape needs a real per-process timeout, and `subprocess.run(timeout=)`
alone is not enough: it only guarantees the *direct* child is signalled,
not any of *its* children (an MCP server subprocess an agent CLI spawned,
for instance) - orphaning them. This module runs the command in its own
process group and kills the whole group.

    timeout fires
      -> SIGTERM the process group (graceful)
      -> wait a short grace period
      -> SIGKILL the process group if it hasn't died

Pair this with resilience.run_step(hard_timeout=False) - run_with_timeout
is itself the real timeout enforcement; a second, overlapping thread-based
timeout racing it (resilience's own hard_timeout=True mode) would only
add a background thread that might still be "cleaning up" after
run_step() has already returned control to the caller. Use hard_timeout=
True instead for a connector that never shells out at all - see
resilience.py's own docstring for that split.
"""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class SubprocessResult:
    returncode: int
    stdout: str
    stderr: str


class SubprocessTimeoutExpired(Exception):
    """Raised when the command did not finish within `timeout` seconds.
    By the time this is raised, the process group has already been sent
    SIGTERM (and SIGKILL if it didn't respond) - there is no orphaned
    process left running when this exception reaches the caller."""

    def __init__(self, cmd: list[str], timeout: float, stdout: str = "", stderr: str = ""):
        super().__init__(f"Command {cmd!r} timed out after {timeout}s")
        self.cmd = cmd
        self.timeout = timeout
        self.stdout = stdout
        self.stderr = stderr


def run_with_timeout(
    cmd: list[str],
    *,
    timeout: float,
    cwd: Optional[str] = None,
    env: Optional[dict] = None,
    kill_grace_seconds: float = 5.0,
) -> SubprocessResult:
    """Run `cmd` with a real, enforced wall-clock timeout. On timeout, the
    entire process group is terminated - not just the direct child - so a
    connector that shells out to something that itself spawns helper
    processes can never leave orphans running after this call returns.
    Raises SubprocessTimeoutExpired on timeout (after the kill has already
    completed), or returns a SubprocessResult with whatever the process
    actually exited with otherwise. Never raises for a non-zero exit code
    on its own - a caller decides what that means (see
    ConnectorReportedError for the structured-failure-from-inside case)."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True,  # its own process group, not this one
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_group(proc, grace_seconds=kill_grace_seconds)
        try:
            stdout, stderr = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise SubprocessTimeoutExpired(cmd, timeout, stdout=stdout, stderr=stderr)

    return SubprocessResult(returncode=proc.returncode, stdout=stdout, stderr=stderr)


def _kill_process_group(proc: subprocess.Popen, *, grace_seconds: float) -> None:
    """SIGTERM the whole process group first (graceful), escalate to
    SIGKILL if it hasn't died within grace_seconds. Kills the direct
    child AND anything it spawned - not just the one PID `proc.kill()`
    alone would reach."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        pass
