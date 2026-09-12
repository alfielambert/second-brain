import json
import threading
from pathlib import Path

import pytest

from second_brain import health
from second_brain.health import _cli_mark_checked
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


def _run_cli(args, capsys):
    try:
        _cli_mark_checked(args)
        code = None
    except SystemExit as e:
        code = e.code
    out = capsys.readouterr()
    return code, out.out, out.err


# --- atomic writes ---

def test_state_write_is_atomic_temp_file_and_rename(vault):
    """update_state uses tempfile.mkstemp + os.replace, not an in-place
    edit - a crash mid-write can never leave connectors.json truncated.
    We can't easily simulate a real crash, but we can prove the write
    path never touches the real file directly by checking no stray .tmp
    file survives a normal write and the file is valid JSON immediately
    after every call."""
    for i in range(5):
        health.mark_checked("capture", "healthy", vault_root=vault, claims_emitted=i)
        state_file = vault / "ClaimStore" / "state" / "connectors.json"
        # the file is always fully valid JSON between writes - never
        # half-written, never containing a temp-file artifact
        json.loads(state_file.read_text())
        assert not list(state_file.parent.glob(".connectors.*.tmp"))


def test_concurrent_writes_do_not_corrupt_the_state_file(vault):
    """Several threads writing different connectors' state at once must
    never interleave into invalid JSON - the flock serializes them."""
    errors = []

    def _write(connector, n):
        try:
            for i in range(20):
                health.mark_checked(connector, "healthy", vault_root=vault, claims_emitted=i)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=_write, args=(f"connector-{i}", i)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    state_file = vault / "ClaimStore" / "state" / "connectors.json"
    data = json.loads(state_file.read_text())  # never raises - always valid JSON
    assert len(data) == 6


# --- current_no_change is distinct from failed ---

def test_current_no_change_is_not_failed():
    assert "current_no_change" in health.VALID_STATUSES
    assert "current_no_change" != "failed"


def test_current_no_change_advances_last_success_like_healthy_does(vault):
    """'Nothing new to ingest' must count as a healthy check for staleness
    purposes - a connector correctly reporting current_no_change every day
    must never be flagged stale just because it never has new data."""
    health.mark_checked("capture", "current_no_change", vault_root=vault)
    state = health.get_state("capture", vault_root=vault)
    assert state["status"] == "current_no_change"
    assert state["last_success"] is not None  # advances, same as "healthy" would


def test_failed_does_not_advance_last_success(vault):
    health.mark_checked("capture", "healthy", vault_root=vault)
    healthy_success_time = health.get_state("capture", vault_root=vault)["last_success"]

    health.mark_checked("capture", "failed", vault_root=vault, error="boom")
    state = health.get_state("capture", vault_root=vault)
    assert state["status"] == "failed"
    assert state.get("last_success") == healthy_success_time  # unchanged - a failed check is not a success


# --- mark-checked CLI ---

def test_cli_mark_checked_success(vault, capsys, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_VAULT", str(vault))
    code, out, err = _run_cli(["capture", "healthy", '{"claims_emitted": 3}'], capsys)
    assert code is None
    result = json.loads(out)
    assert result["status"] == "healthy"
    assert result["claims_emitted"] == 3


def test_cli_mark_checked_rejects_unknown_status(vault, capsys, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_VAULT", str(vault))
    code, out, err = _run_cli(["capture", "not-a-real-status"], capsys)
    assert code == 2
    assert health.get_state("capture", vault_root=vault) == {}  # nothing written


def test_cli_mark_checked_rejects_malformed_json(vault, capsys, monkeypatch):
    monkeypatch.setenv("SECOND_BRAIN_VAULT", str(vault))
    code, out, err = _run_cli(["capture", "healthy", "{not json"], capsys)
    assert code == 2
    assert health.get_state("capture", vault_root=vault) == {}
