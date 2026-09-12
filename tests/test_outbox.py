from pathlib import Path

import pytest

from second_brain import claimstore, outbox
from second_brain.vault import init_vault


@pytest.fixture
def vault(tmp_path) -> Path:
    return init_vault(tmp_path / "vault")


class FakeNotifier:
    """Minimal Notifier for tests - records what it was asked to send,
    and can be told to fail on demand for specific proposal_ids."""

    def __init__(self, fail_for: set[str] = frozenset()):
        self.sent: list[dict] = []
        self.texts: list[str] = []
        self._fail_for = fail_for

    def send_proposal(self, proposal: dict) -> None:
        if proposal["proposal_id"] in self._fail_for:
            raise RuntimeError("simulated delivery failure")
        self.sent.append(proposal)

    def send_text(self, text: str) -> None:
        self.texts.append(text)


def _make_pending_proposal(vault: Path, content: str = "A proposal.") -> str:
    claim = claimstore.append_claim(
        vault_root=vault, connector="capture",
        source={"id": f"src-{content}", "type": "capture", "occurred_at": None, "title": "t"},
        claim_type="entity_update", entities=[], content=content,
        evidence=[{"text": content, "speaker": None, "location": None}],
        confidence="high", operation="create_entity", target_note=None,
    )
    claim_id = claim["claim_id"]
    claimstore.append_event(
        vault_root=vault, event_type="proposal-created", actor="kep", claim_id=claim_id,
        payload={"action": "propose", "reason": "new entity"},
    )
    proposal_path = vault / "Proposals" / f"{claim_id}.md"
    proposal_path.parent.mkdir(parents=True, exist_ok=True)
    proposal_path.write_text(f"---\nclaim_id: {claim_id}\n---\n\n## Content\n\n{content}\n")
    return claim_id


# --- delivery + idempotency ---

def test_pending_proposal_is_sent_and_marked(vault):
    claim_id = _make_pending_proposal(vault)
    notifier = FakeNotifier()

    result = outbox.deliver_pending_proposals(notifier, vault_root=vault)

    assert result["sent"] == 1
    assert result["failed"] == 0
    assert len(notifier.sent) == 1
    assert notifier.sent[0]["proposal_id"] == claim_id
    events = [e for e in claimstore.get_events_for_claim(claim_id, vault_root=vault) if e["event_type"] == "proposal-sent"]
    assert len(events) == 1


def test_proposal_sent_exactly_once_across_repeated_calls(vault):
    """Calling deliver_pending_proposals() again - this run, or a later
    one - must never re-send anything already marked proposal-sent."""
    claim_id = _make_pending_proposal(vault)
    notifier = FakeNotifier()

    outbox.deliver_pending_proposals(notifier, vault_root=vault)
    result2 = outbox.deliver_pending_proposals(notifier, vault_root=vault)

    assert result2["sent"] == 0  # nothing left to send
    assert len(notifier.sent) == 1  # still only ever sent once
    events = [e for e in claimstore.get_events_for_claim(claim_id, vault_root=vault) if e["event_type"] == "proposal-sent"]
    assert len(events) == 1


# --- one failure doesn't block the rest, and stays pending ---

def test_send_failure_leaves_the_item_pending(vault):
    claim_id = _make_pending_proposal(vault, content="Will fail")
    notifier = FakeNotifier(fail_for={claim_id})

    result = outbox.deliver_pending_proposals(notifier, vault_root=vault)

    assert result["failed"] == 1
    assert result["sent"] == 0
    events = [e for e in claimstore.get_events_for_claim(claim_id, vault_root=vault) if e["event_type"] == "proposal-sent"]
    assert len(events) == 0  # not marked sent - stays pending for the next attempt


def test_send_failure_does_not_prevent_later_items_being_attempted(vault):
    bad_id = _make_pending_proposal(vault, content="Will fail")
    good_id = _make_pending_proposal(vault, content="Will succeed")
    notifier = FakeNotifier(fail_for={bad_id})

    result = outbox.deliver_pending_proposals(notifier, vault_root=vault)

    assert result["failed"] == 1
    assert result["sent"] == 1
    assert good_id in [d["claim_id"] for d in result["details"] if d["sent"]]


def test_a_failed_item_is_retried_on_the_next_call_once_the_underlying_problem_is_gone(vault):
    claim_id = _make_pending_proposal(vault)
    flaky = FakeNotifier(fail_for={claim_id})

    result1 = outbox.deliver_pending_proposals(flaky, vault_root=vault)
    assert result1["failed"] == 1

    reliable = FakeNotifier()  # simulates the transient problem being gone now
    result2 = outbox.deliver_pending_proposals(reliable, vault_root=vault)
    assert result2["sent"] == 1


# --- rendering ---

def test_escape_html_neutralises_the_three_meaningful_characters():
    assert outbox.escape_html("<script>&\"'") == "&lt;script&gt;&amp;\"'"


def test_render_proposal_text_never_exceeds_the_length_cap():
    huge = {"proposal_id": "x", "confidence": "high", "proposed_change": "A" * 10000, "reasoning": "B" * 10000}
    text = outbox.render_proposal_text(huge)
    assert len(text) <= outbox.TELEGRAM_MAX_MESSAGE_CHARS + len("\n... (truncated)")
