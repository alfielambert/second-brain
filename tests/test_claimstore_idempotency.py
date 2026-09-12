from pathlib import Path

import pytest

from second_brain import claimstore, kep
from second_brain.cli import _apply_claim, _create_proposal
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


def _claim_kwargs(**overrides):
    base = dict(
        connector="capture",
        source={"id": "note-1", "type": "capture", "occurred_at": "2026-08-01T00:00:00Z", "title": "Note"},
        claim_type="fact",
        entities=[],
        content="A fact worth recording.",
        evidence=[{"text": "A fact worth recording.", "speaker": None, "location": None}],
        confidence="high",
        operation="enrich_existing",
        target_note="Insights/Example.md",
    )
    base.update(overrides)
    return base


# --- append_claim dedupe ---

def test_first_write_is_new(vault):
    record = claimstore.append_claim(vault_root=vault, **_claim_kwargs())
    assert record["_new"] is True
    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 1


def test_retry_after_partial_progress_does_not_duplicate_a_claim(vault):
    """Simulates the real failure mode connectors/capture.py's own
    discover()/update_cursor() split can hit: a sync step extracts a
    claim, then crashes before update_cursor() runs. The retry
    re-discovers the same source item from scratch and tries to extract
    'the same' claim again."""
    first = claimstore.append_claim(vault_root=vault, **_claim_kwargs())
    second = claimstore.append_claim(vault_root=vault, **_claim_kwargs())  # retry: identical connector/source/operation

    assert first["claim_id"] == second["claim_id"]
    assert second["_new"] is False
    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 1  # exactly one line on disk


def test_different_operation_same_source_is_not_a_duplicate(vault):
    a = claimstore.append_claim(vault_root=vault, **_claim_kwargs(operation="enrich_existing"))
    b = claimstore.append_claim(vault_root=vault, **_claim_kwargs(operation="create_entity", content="Also new."))
    assert a["claim_id"] != b["claim_id"]
    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 2


def test_explicit_dedupe_key_distinguishes_multi_claim_sources(vault):
    """One source can legitimately yield more than one claim sharing an
    operation - see examples/acme.py's kickoff-note claims for a real
    case this protects."""
    a = claimstore.append_claim(vault_root=vault, **_claim_kwargs(
        operation="create_entity", dedupe_key="capture:note-1:create_entity:person-a", content="Person A appears.",
    ))
    b = claimstore.append_claim(vault_root=vault, **_claim_kwargs(
        operation="create_entity", dedupe_key="capture:note-1:create_entity:person-b", content="Person B appears.",
    ))
    assert a["claim_id"] != b["claim_id"]
    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 2

    # retrying with the SAME explicit key is still a duplicate
    a_retry = claimstore.append_claim(vault_root=vault, **_claim_kwargs(
        operation="create_entity", dedupe_key="capture:note-1:create_entity:person-a", content="Person A appears.",
    ))
    assert a_retry["claim_id"] == a["claim_id"]
    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 2


# --- KEP-routing idempotency ---

def test_claim_needs_kep_routing_true_before_any_decision(vault):
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs())
    assert claimstore.claim_needs_kep_routing(claim["claim_id"], vault_root=vault) is True
    assert claimstore.get_kep_decision(claim["claim_id"], vault_root=vault) is None


def test_claim_needs_kep_routing_false_after_decision_recorded(vault):
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs())
    claimstore.append_event(
        vault_root=vault, event_type="kep-decision", actor="kep", claim_id=claim["claim_id"],
        payload={"action": "propose", "reason": "needs review"},
    )
    assert claimstore.claim_needs_kep_routing(claim["claim_id"], vault_root=vault) is False
    assert claimstore.get_kep_decision(claim["claim_id"], vault_root=vault) == {"action": "propose", "reason": "needs review"}


# --- proposal idempotency (does not duplicate a proposal/outbox item) ---

def test_create_proposal_writes_file_and_event_once(vault):
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs(operation="create_entity", confidence="high"))
    decision = kep.Decision(action="propose", reason="new entity", requires_approval=True)

    _create_proposal(vault, claim, decision)

    proposal_path = vault / "Proposals" / f"{claim['claim_id']}.md"
    assert proposal_path.exists()
    events = [e for e in claimstore.get_events_for_claim(claim["claim_id"], vault_root=vault) if e["event_type"] == "proposal-created"]
    assert len(events) == 1


def test_create_proposal_retry_does_not_duplicate_file_or_event(vault):
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs(operation="create_entity", confidence="high"))
    decision = kep.Decision(action="propose", reason="new entity", requires_approval=True)

    _create_proposal(vault, claim, decision)
    original_mtime = (vault / "Proposals" / f"{claim['claim_id']}.md").stat().st_mtime_ns
    _create_proposal(vault, claim, decision)  # simulated retry after an interruption

    events = [e for e in claimstore.get_events_for_claim(claim["claim_id"], vault_root=vault) if e["event_type"] == "proposal-created"]
    assert len(events) == 1  # not two
    assert len(list((vault / "Proposals").glob("*.md"))) == 1  # not two files
    # the retry didn't even rewrite the file
    assert (vault / "Proposals" / f"{claim['claim_id']}.md").stat().st_mtime_ns == original_mtime


# --- auto-apply idempotency ---

def test_apply_claim_writes_durable_write_event_once(vault):
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs())
    applied = _apply_claim(vault, claim, actor="kep")
    assert applied is True

    events = [e for e in claimstore.get_events_for_claim(claim["claim_id"], vault_root=vault) if e["event_type"] == "durable-write"]
    assert len(events) == 1


def test_apply_claim_retry_is_a_safe_no_op(vault):
    """Without this guard, calling `second-brain approve` twice for the
    same claim_id - a plausible real mistake - would append a second
    ## Update block to the target note (notes.write_note appends rather
    than overwrites) and a second durable-write event."""
    claim = claimstore.append_claim(vault_root=vault, **_claim_kwargs(target_note="Insights/Retry Example.md"))

    first = _apply_claim(vault, claim, actor="kep")
    second = _apply_claim(vault, claim, actor="kep")  # e.g. `second-brain approve` run twice

    assert first is True
    assert second is False

    note_text = (vault / "Insights" / "Retry Example.md").read_text()
    assert note_text.count("## Update") == 0  # first write creates the note fresh, no Update block yet
    assert note_text.count("A fact worth recording.") == 1  # content appears exactly once

    events = [e for e in claimstore.get_events_for_claim(claim["claim_id"], vault_root=vault) if e["event_type"] == "durable-write"]
    assert len(events) == 1


def test_full_propose_flow_survives_a_retry_with_no_duplicates(vault):
    """End-to-end: attempt 1 extracts a claim, routes it, creates a
    proposal, then 'crashes'. Attempt 2 (the retry) re-extracts the same
    claim from scratch and re-runs the same routing/proposal logic. Final
    state must show exactly one of everything."""
    kwargs = _claim_kwargs(operation="create_entity", confidence="high")

    # --- attempt 1 ---
    claim1 = claimstore.append_claim(vault_root=vault, **kwargs)
    decision = kep.classify_claim(claim1)
    claimstore.append_event(
        vault_root=vault, event_type="kep-decision", actor="kep", claim_id=claim1["claim_id"],
        payload={"action": decision.action, "reason": decision.reason},
    )
    _create_proposal(vault, claim1, decision)
    # (simulated crash here)

    # --- attempt 2: retry re-runs the whole step from scratch ---
    claim2 = claimstore.append_claim(vault_root=vault, **kwargs)
    assert claim2["claim_id"] == claim1["claim_id"]
    assert claim2["_new"] is False

    if claimstore.claim_needs_kep_routing(claim2["claim_id"], vault_root=vault):
        decision2 = kep.classify_claim(claim2)
        claimstore.append_event(
            vault_root=vault, event_type="kep-decision", actor="kep", claim_id=claim2["claim_id"],
            payload={"action": decision2.action, "reason": decision2.reason},
        )
    else:
        payload = claimstore.get_kep_decision(claim2["claim_id"], vault_root=vault)
        decision2 = kep.Decision(action=payload["action"], reason=payload["reason"], requires_approval=False)
    _create_proposal(vault, claim2, decision2)

    assert len(list(claimstore.iter_all_claims(vault_root=vault))) == 1
    all_events = list(claimstore.iter_all_events(vault_root=vault))
    assert len([e for e in all_events if e["event_type"] == "kep-decision"]) == 1
    assert len([e for e in all_events if e["event_type"] == "proposal-created"]) == 1
    assert len(list((vault / "Proposals").glob("*.md"))) == 1
