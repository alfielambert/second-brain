"""
Concurrency lock - prevents two overlapping sync runs (a manual run and a
scheduled one firing at the same time, or a retry while a prior run is
still going).

Non-blocking flock: a second run that can't acquire the lock exits
immediately with a clear "already running" message rather than queuing or
silently doing nothing. Stale locks (holder process no longer exists) are
detected and cleaned up automatically.
"""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from second_brain.vault import find_vault_root


class AlreadyRunning(Exception):
    def __init__(self, holder_pid: int):
        self.holder_pid = holder_pid
        super().__init__(f"sync already running (pid {holder_pid})")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


@contextmanager
def sync_lock(vault_root: Optional[Path] = None, name: str = "daily_sync"):
    root = vault_root or find_vault_root()
    lock_path = root / "ClaimStore" / "state" / f"{name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lockf = None
    for attempt in (1, 2):  # second attempt only fires after stale-lock cleanup
        lockf = open(lock_path, "a+")
        try:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except BlockingIOError:
            lockf.seek(0)
            content = lockf.read().strip()
            holder_pid = int(content) if content.isdigit() else -1
            lockf.close()
            if attempt == 1 and holder_pid > 0 and not _pid_alive(holder_pid):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise AlreadyRunning(holder_pid)
    else:
        raise AlreadyRunning(-1)

    try:
        lockf.seek(0)
        lockf.truncate()
        lockf.write(str(os.getpid()))
        lockf.flush()
        yield
    finally:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        lockf.close()
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
