import argparse
import time
from pathlib import Path

import pytest
import yaml

from second_brain import claimstore, health
from second_brain.cli import _connector_timeout, cmd_sync
from second_brain.connectors import capture, x_bookmarks
from second_brain.vault import CONFIG_NAME, init_vault, load_config


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


def _sync_args(connector: str) -> argparse.Namespace:
    return argparse.Namespace(connector=connector, limit=None)


# --- per-connector budgets, resolved from config ---

def test_connector_timeout_reads_per_connector_config_value():
    config = {"connectors": {"capture": {"session_timeout_seconds": 42}, "x_bookmarks": {"session_timeout_seconds": 777}}}
    assert _connector_timeout(config, "capture") == 42.0
    assert _connector_timeout(config, "x_bookmarks") == 777.0


def test_connector_timeout_falls_back_to_default_config_when_unset():
    from second_brain.vault import default_config
    assert _connector_timeout({}, "capture") == default_config()["connectors"]["capture"]["session_timeout_seconds"]


def test_connector_a_and_b_receive_different_budgets_end_to_end(vault, monkeypatch):
    """Through the real cmd_sync path (not a direct resilience.run_step
    call): capture is given a budget too tight for a deliberately slow
    discover(); x_bookmarks is given a wide budget for an equally slow
    discover(). Only the tightly-budgeted one should fail on timeout -
    proving the two connectors' budgets are genuinely independent, not a
    single shared value."""
    config_path = vault / CONFIG_NAME
    config = load_config(vault)
    config["connectors"]["capture"]["session_timeout_seconds"] = 0.05
    config["connectors"]["x_bookmarks"] = {"enabled": True, "session_timeout_seconds": 2.0}
    config_path.write_text(yaml.safe_dump(config, sort_keys=False))

    def slow_discover(root, limit=None):
        time.sleep(0.2)
        return []

    monkeypatch.setattr(capture, "discover", slow_discover)
    monkeypatch.setattr(x_bookmarks, "discover", slow_discover)
    monkeypatch.chdir(vault)

    with pytest.raises(SystemExit) as exc_info:
        cmd_sync(_sync_args("capture"))
    assert exc_info.value.code == 1
    assert health.get_state("capture", vault_root=vault)["status"] == "failed"

    cmd_sync(_sync_args("x_bookmarks"))  # must NOT raise - its own budget covers the same 0.2s delay
    assert health.get_state("x_bookmarks", vault_root=vault)["status"] == "current_no_change"


# --- failed sync leaves local governed knowledge untouched ---

def test_failed_sync_does_not_touch_already_durable_knowledge(vault, monkeypatch):
    """Write one durable note via the normal claim -> route -> apply path,
    then make the SAME connector fail on its next sync. The pre-existing
    durable note and claim must be completely unaffected - a distribution/
    execution failure is not a knowledge-integrity risk."""
    from second_brain import kep
    from second_brain.cli import _apply_claim

    claim = claimstore.append_claim(
        vault_root=vault, connector="capture",
        source={"id": "existing-note", "type": "capture", "occurred_at": None, "title": "t"},
        claim_type="fact", entities=[], content="Durable fact from before the failure.",
        evidence=[{"text": "Durable fact from before the failure.", "speaker": None, "location": None}],
        confidence="high", operation="enrich_existing", target_note="Insights/Durable.md",
    )
    _apply_claim(vault, claim, actor="kep")
    note_before = (vault / "Insights" / "Durable.md").read_text()
    claims_before = list(claimstore.iter_all_claims(vault_root=vault))

    def broken_discover(root, limit=None):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr(capture, "discover", broken_discover)
    monkeypatch.chdir(vault)

    with pytest.raises(SystemExit):
        cmd_sync(_sync_args("capture"))

    assert (vault / "Insights" / "Durable.md").read_text() == note_before  # byte-for-byte unchanged
    assert list(claimstore.iter_all_claims(vault_root=vault)) == claims_before  # no claim lost or altered
    assert health.get_state("capture", vault_root=vault)["status"] == "failed"


def test_sync_dedupes_claims_across_a_retry_via_the_real_cli_path(vault, monkeypatch):
    """discover() finds the same item twice in a row (simulating: item
    processed, crash before update_cursor, retry re-discovers it) - the
    real cmd_sync path must not duplicate the resulting claim."""
    call_count = {"n": 0}
    item = {"path": "note.md", "name": "note.md"}

    def discover_same_item_every_time(root, limit=None):
        call_count["n"] += 1
        return [item]

    def fetch(_item):
        return {**_item, "text": "Some captured text."}

    def normalise(raw):
        return {"source": {"id": raw["path"], "type": "capture", "occurred_at": None, "title": raw["name"], "url": None}, "text": raw["text"]}

    def extract_claims(normalised):
        return [{
            "connector": "capture", "source": normalised["source"], "claim_type": "signal",
            "entities": [], "content": normalised["text"], "evidence": [{"text": normalised["text"], "speaker": None, "location": None}],
            "confidence": "low", "operation": "weak_inference",
        }]

    def update_cursor(root, _item):
        pass  # simulates the cursor step never completing

    monkeypatch.setattr(capture, "discover", discover_same_item_every_time)
    monkeypatch.setattr(capture, "fetch", fetch)
    monkeypatch.setattr(capture, "normalise", normalise)
    monkeypatch.setattr(capture, "extract_claims", extract_claims)
    monkeypatch.setattr(capture, "update_cursor", update_cursor)
    monkeypatch.chdir(vault)

    cmd_sync(_sync_args("capture"))
    cmd_sync(_sync_args("capture"))  # "retry" - discover() finds the same un-advanced item again

    claims = [c for c in claimstore.iter_all_claims(vault_root=vault) if c["connector"] == "capture"]
    assert len(claims) == 1  # not two
