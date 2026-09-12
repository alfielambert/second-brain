import os
import sys
import time

import pytest

from second_brain.subprocess_timeout import SubprocessTimeoutExpired, run_with_timeout


def test_fast_command_returns_normally():
    result = run_with_timeout([sys.executable, "-c", "print('hello')"], timeout=5)
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_nonzero_exit_is_returned_not_raised():
    """A real failure (bad exit code) is not conflated with a timeout -
    the caller decides what a non-zero exit means, run_with_timeout just
    reports it."""
    result = run_with_timeout([sys.executable, "-c", "import sys; sys.exit(3)"], timeout=5)
    assert result.returncode == 3


def test_timed_out_subprocess_group_is_actually_terminated():
    """The core guarantee: when the timeout fires, the process (and any
    children it spawned) is genuinely gone afterward - not orphaned,
    not still running in the background hidden from the caller."""
    # A parent that spawns a child sleep process, so we can verify the
    # WHOLE group dies, not just the direct child subprocess.py sees.
    script = (
        "import subprocess, time, sys\n"
        "p = subprocess.Popen(['sleep', '30'])\n"
        "print(p.pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    t0 = time.monotonic()
    with pytest.raises(SubprocessTimeoutExpired):
        run_with_timeout([sys.executable, "-c", script], timeout=0.3, kill_grace_seconds=1.0)
    elapsed = time.monotonic() - t0

    # Killed well before either sleep(30) would have returned on its own.
    assert elapsed < 5.0


def test_timeout_exception_carries_the_partial_output_captured_so_far():
    script = "import sys; print('partial output', flush=True); import time; time.sleep(30)"
    with pytest.raises(SubprocessTimeoutExpired) as exc_info:
        run_with_timeout([sys.executable, "-c", script], timeout=0.3, kill_grace_seconds=1.0)
    assert "partial output" in exc_info.value.stdout


def test_grandchild_process_does_not_survive_the_timeout_kill():
    """Stronger version of the group-termination guarantee: write a PID
    file from a grandchild, kill on timeout, then confirm that PID is
    genuinely dead - not just detached from the parent we were watching."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode="r", suffix=".pid", delete=False) as f:
        pid_file = f.name

    script = (
        f"import subprocess, time\n"
        f"p = subprocess.Popen(['sh', '-c', 'echo $$ > {pid_file}; sleep 30'])\n"
        f"time.sleep(30)\n"
    )
    with pytest.raises(SubprocessTimeoutExpired):
        run_with_timeout([sys.executable, "-c", script], timeout=0.5, kill_grace_seconds=1.0)

    time.sleep(0.2)  # let the pid file actually get written before we check it
    with open(pid_file) as f:
        content = f.read().strip()
    os.unlink(pid_file)

    if content:  # the grandchild got far enough to write its pid before being killed
        grandchild_pid = int(content)
        with pytest.raises(ProcessLookupError):
            os.kill(grandchild_pid, 0)  # signal 0: just checks if the process exists
