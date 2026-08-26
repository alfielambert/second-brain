"""
Fictional demo dataset - Acme, a mid-market logistics SaaS company
evaluating "Atlas", a fictional product. Used by `second-brain init
--with-sample` to demonstrate the full loop (Claim Store -> KEP -> governed
vault -> compiled context) without needing any real source or API key.

Deliberately mirrors the shape of a real Second Brain's evidence: an
entity-creation claim, a high-confidence enrichment (auto-applies), two
proposals (a Hypothesis and an Insight that partly contradicts it - the
"epistemic audit" pattern), a Decision, a later claim that supersedes that
Decision, and a weak signal that never becomes a proposal at all.
"""

from __future__ import annotations

from pathlib import Path

from second_brain import claimstore


def _claim(**kwargs) -> dict:
    kwargs.setdefault("evidence", [{"text": kwargs["content"], "speaker": None, "location": None}])
    return kwargs


CLAIMS = [
    _claim(
        connector="capture", claim_type="entity_update", operation="create_entity", confidence="high",
        source={"id": "acme-kickoff-note", "type": "capture", "occurred_at": "2026-08-01T09:00:00Z", "title": "Acme kickoff note", "url": None},
        content="Acme is a mid-market logistics SaaS company evaluating Atlas.",
        entities=[{"type": "company", "name": "Acme", "ref": None}],
        target_note="Companies/Acme.md",
    ),
    _claim(
        connector="capture", claim_type="entity_update", operation="create_entity", confidence="high",
        source={"id": "acme-kickoff-note", "type": "capture", "occurred_at": "2026-08-01T09:00:00Z", "title": "Acme kickoff note", "url": None},
        content="Maya Ruiz is CEO of Acme and the primary decision-maker on the Atlas evaluation.",
        entities=[{"type": "person", "name": "Maya Ruiz", "ref": None}, {"type": "company", "name": "Acme", "ref": "Companies/Acme.md"}],
        target_note="People/Maya Ruiz.md",
    ),
    _claim(
        connector="capture", claim_type="entity_update", operation="create_entity", confidence="high",
        source={"id": "acme-kickoff-note", "type": "capture", "occurred_at": "2026-08-01T09:00:00Z", "title": "Acme kickoff note", "url": None},
        content="Daniel Osei is Head of Sales at Acme, championing the Atlas deal internally.",
        entities=[{"type": "person", "name": "Daniel Osei", "ref": None}, {"type": "company", "name": "Acme", "ref": "Companies/Acme.md"}],
        target_note="People/Daniel Osei.md",
    ),
    _claim(
        connector="capture", claim_type="fact", operation="enrich_existing", confidence="high",
        source={"id": "atlas-launch-planning-meeting", "type": "capture", "occurred_at": "2026-08-05T14:00:00Z", "title": "Atlas Launch Planning meeting", "url": None},
        content="At the Atlas Launch Planning meeting, Maya confirmed the target launch date of September 2026.",
        entities=[{"type": "company", "name": "Acme", "ref": "Companies/Acme.md"}],
        target_note="Meetings/Atlas Launch Planning.md",
    ),
    _claim(
        connector="capture", claim_type="hypothesis", operation="create_entity", confidence="medium",
        source={"id": "atlas-launch-planning-meeting", "type": "capture", "occurred_at": "2026-08-05T14:00:00Z", "title": "Atlas Launch Planning meeting", "url": None},
        content="Hypothesis: enterprise users like Acme prefer self-hosting Atlas over a managed/hosted deployment.",
        entities=[{"type": "concept", "name": "self-hosting preference", "ref": None}],
        target_note="Hypotheses/Enterprise Users Prefer Self-Hosting.md",
    ),
    _claim(
        connector="capture", claim_type="insight", operation="create_entity", confidence="medium",
        source={"id": "customer-interview-batch-1", "type": "capture", "occurred_at": "2026-08-12T10:00:00Z", "title": "Customer interview batch (5 interviews)", "url": None},
        content="Insight: across 5 customer interviews, security review timelines - not hosting model - were the actual bottleneck to adoption. Hosting preference was a weaker signal than expected.",
        entities=[{"type": "concept", "name": "adoption bottleneck", "ref": None}],
        target_note="Insights/Security Review Is The Adoption Bottleneck.md",
    ),
    _claim(
        connector="capture", claim_type="decision", operation="create_entity", confidence="high",
        source={"id": "atlas-launch-planning-meeting", "type": "capture", "occurred_at": "2026-08-05T14:00:00Z", "title": "Atlas Launch Planning meeting", "url": None},
        content="Decision: Atlas launches in September 2026.",
        entities=[{"type": "company", "name": "Acme", "ref": "Companies/Acme.md"}],
        target_note="Decisions/Atlas Launch Date.md",
    ),
    _claim(
        connector="capture", claim_type="decision", operation="supersede", confidence="high",
        source={"id": "acme-followup-call", "type": "capture", "occurred_at": "2026-08-20T11:00:00Z", "title": "Acme follow-up call", "url": None},
        content="Decision: the Atlas launch moves from September to October 2026 - the security review (see Insight: adoption bottleneck) is taking longer than planned.",
        entities=[{"type": "company", "name": "Acme", "ref": "Companies/Acme.md"}],
        target_note="Decisions/Atlas Launch Date.md",
    ),
    _claim(
        connector="capture", claim_type="signal", operation="weak_inference", confidence="low",
        source={"id": "acme-followup-call", "type": "capture", "occurred_at": "2026-08-20T11:00:00Z", "title": "Acme follow-up call", "url": None},
        content="Daniel mentioned churn risk 'feels like it's rising' among similar accounts - no numbers given.",
        entities=[{"type": "person", "name": "Daniel Osei", "ref": "People/Daniel Osei.md"}],
        target_note=None,
    ),
]


def seed(vault_root: Path) -> list[dict]:
    written = []
    for claim in CLAIMS:
        written.append(claimstore.append_claim(vault_root=vault_root, **claim))
    return written
