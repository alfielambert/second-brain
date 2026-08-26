"""
Connector health + cursor state - ClaimStore/state/connectors.json.

One JSON object per connector, holding both the idempotency cursor (e.g.
last-seen source ID) AND health-visibility fields:

  last_checked, last_success, claims_emitted, status

status is one of: healthy | current_no_change | degraded | failed | stale |
auth_required. "Nothing new to ingest" is current_no_change, never failed -
that distinction is what lets a watchdog alert on real breakage without
also alerting every time a connector simply has nothing new.

Writes are read-modify-write under an flock, using a temp-file + atomic
rename so a crash mid-write can never leave connectors.json truncated or
half-written.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from second_brain.vault import find_vault_root

VALID_STATUSES = {"healthy", "current_no_change", "degraded", "failed", "stale", "auth_required"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_paths(vault_root: Optional[Path] = None) -> tuple[Path, Path]:
    root = vault_root or find_vault_root()
    state_dir = root / "ClaimStore" / "state"
    return state_dir / "connectors.json", state_dir / ".connectors.lock"


def _read_raw(vault_root: Optional[Path] = None) -> dict:
    state_file, _ = _state_paths(vault_root)
    if not state_file.exists():
        return {}
    with open(state_file, "r", encoding="utf-8") as f:
        content = f.read().strip()
        return json.loads(content) if content else {}


def _write_raw(data: dict, vault_root: Optional[Path] = None) -> None:
    state_file, _ = _state_paths(vault_root)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(state_file.parent), prefix=".connectors.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, state_file)  # atomic on the same filesystem
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def get_state(connector: str, vault_root: Optional[Path] = None) -> dict:
    return _read_raw(vault_root).get(connector, {})


def all_states(vault_root: Optional[Path] = None) -> dict:
    return _read_raw(vault_root)


def update_state(connector: str, vault_root: Optional[Path] = None, **fields: Any) -> dict:
    """Read-modify-write one connector's state block under an exclusive lock."""
    _, lock_file = _state_paths(vault_root)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "w") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_raw(vault_root)
            block = data.get(connector, {})
            block.update(fields)
            data[connector] = block
            _write_raw(data, vault_root)
            return block
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def mark_checked(connector: str, status: str, vault_root: Optional[Path] = None, **extra: Any) -> dict:
    if status not in VALID_STATUSES:
        raise ValueError(f"status {status!r} not in {sorted(VALID_STATUSES)}")
    fields = {"last_checked": _now_iso(), "status": status, **extra}
    if status in {"healthy", "current_no_change"}:
        fields["last_success"] = _now_iso()
    return update_state(connector, vault_root=vault_root, **fields)


def stale_connectors(max_age_hours: int = 36, vault_root: Optional[Path] = None) -> list[dict]:
    """Connectors whose last_success is older than max_age_hours, or that
    have never succeeded. Used by the independent watchdog."""
    now = datetime.now(timezone.utc)
    out = []
    for name, block in _read_raw(vault_root).items():
        last_success = block.get("last_success")
        if not last_success:
            out.append({"connector": name, "age_hours": None, "reason": "never succeeded"})
            continue
        dt = datetime.strptime(last_success, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age_hours = (now - dt).total_seconds() / 3600
        if age_hours > max_age_hours:
            out.append({"connector": name, "age_hours": round(age_hours, 1), "reason": "stale"})
    return out
