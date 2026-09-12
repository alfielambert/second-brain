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
import sys
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


# --- CLI ---------------------------------------------------------------
#
# Today's shipped connectors (capture, x_bookmarks) call mark_checked()
# directly as a plain Python function - they never need this CLI. It
# exists for the connector shape docs/connector-contract.md documents but
# doesn't ship: one that runs as an external subprocess (an agent CLI, an
# MCP-backed session). That kind of connector can only report its own
# health/cursor state back to the vault through some allowlisted,
# invokable surface - not by importing this module directly, since it's
# running in a different process. `python -m second_brain.health
# mark-checked <connector> <status> <json>` is that surface: a single,
# fixed, easy-to-allowlist command shape, so a connector session never has
# to improvise how to report its own state.

def _cli_mark_checked(args: list[str]) -> None:
    """mark-checked <connector> <status> [<json-extra-fields>|-]

    Wraps mark_checked() directly - no write logic is reimplemented here.
    Extra fields are one JSON object, as a literal argument or read from
    stdin with '-'. Prints the updated state block as JSON on success.
    Exits 2 on invalid input (unknown status, malformed JSON, or a JSON
    value that isn't an object) and 1 if the write itself fails."""
    if len(args) < 2:
        print("usage: python -m second_brain.health mark-checked <connector> <status> [<json-extra-fields>|-]", file=sys.stderr)
        sys.exit(2)

    connector, status = args[0], args[1]
    if status not in VALID_STATUSES:
        print(f"error: status {status!r} not in {sorted(VALID_STATUSES)}", file=sys.stderr)
        sys.exit(2)

    extra: dict = {}
    if len(args) >= 3:
        raw = sys.stdin.read() if args[2] == "-" else args[2]
        raw = raw.strip()
        if raw:
            try:
                extra = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"error: extra fields must be valid JSON: {e}", file=sys.stderr)
                sys.exit(2)
            if not isinstance(extra, dict):
                print(f"error: extra fields JSON must be an object, got {type(extra).__name__}", file=sys.stderr)
                sys.exit(2)

    try:
        result = mark_checked(connector, status, **extra)
    except Exception as e:  # noqa: BLE001 - any write failure must exit non-zero
        print(f"error: write failed: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m second_brain.health <mark-checked|stale|CONNECTOR> [args]", file=sys.stderr)
        sys.exit(2)
    if sys.argv[1] == "mark-checked":
        _cli_mark_checked(sys.argv[2:])
    elif sys.argv[1] == "stale":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 36
        print(json.dumps(stale_connectors(hours), indent=2))
    else:
        print(json.dumps(get_state(sys.argv[1]), indent=2))


if __name__ == "__main__":
    main()
