import subprocess
import sys
from pathlib import Path

import pytest

from second_brain import claimstore, kep
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


def test_claim_is_immutable_status_derived_from_events(vault):
    claim = claimstore.append_claim(
        vault_root=vault, connector="capture",
        source={"id": "x", "type": "capture", "occurred_at": None, "title": "t", "url": None},
        claim_type="fact", entities=[], content="hello", evidence=[],
        confidence="high", operation="enrich_existing",
    )
    assert claimstore.current_status(claim["claim_id"], vault_root=vault) == "pending"

    claimstore.append_event(
        vault_root=vault, event_type="auto-applied", actor="kep", claim_id=claim["claim_id"], payload={},
    )
    assert claimstore.current_status(claim["claim_id"], vault_root=vault) == "auto_applied"

    # the claim record itself never changes
    reloaded = claimstore.get_claim(claim["claim_id"], vault_root=vault)
    assert reloaded["content"] == "hello"


@pytest.mark.parametrize("operation,confidence,claim_type,expected_action", [
    ("weak_inference", "high", "fact", "signal"),
    ("enrich_existing", "high", "fact", "auto_apply"),
    ("enrich_existing", "medium", "fact", "propose"),
    ("create_entity", "high", "entity_update", "propose"),
    ("supersede", "high", "decision", "supersede_candidate"),
])
def test_kep_routing_table(operation, confidence, claim_type, expected_action):
    decision = kep.classify_claim({"operation": operation, "confidence": confidence, "claim_type": claim_type})
    assert decision.action == expected_action


def test_cli_full_loop_produces_durable_pack(tmp_path):
    vault_path = tmp_path / "vault"
    run = lambda *a: subprocess.run(
        [sys.executable, "-m", "second_brain.cli", *a], cwd=vault_path if vault_path.exists() else tmp_path,
        capture_output=True, text=True, check=True,
    )

    subprocess.run(
        [sys.executable, "-m", "second_brain.cli", "init", str(vault_path), "--with-sample"],
        capture_output=True, text=True, check=True,
    )
    run("route")
    run("approve", "--all-pending")
    result = run("compile", "--target", "founder")

    pack = vault_path / "Packs" / "founder.md"
    assert pack.exists()
    text = pack.read_text()
    assert "Compile Report" in text
    assert "Included: 7 durable claim(s)" in text  # 8 non-signal claims minus 1 superseded
