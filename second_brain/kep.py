"""
KEP - Knowledge Evolution Protocol - executable governance.

This is deliberately NOT a model call. An extraction step (which may well
use an LLM - see claude/README.md) decides WHAT a claim is: its type,
operation, entities, confidence. This module decides WHERE it goes, as a
pure lookup table over (operation, claim_type, confidence). Keeping routing
deterministic means it's testable, auditable, and never silently drifts
between runs the way a second judgement call could.

classify_claim() never mutates the claim. It returns a Decision; the caller
is responsible for calling claimstore.append_event(event_type="kep-decision", ...)
to record it, and then executing the consequence itself (an auto-apply
write, or a Proposals/*.md file for human review).
"""

from __future__ import annotations

from dataclasses import dataclass

# Operations that are structurally incapable of being auto-applied, no
# matter how high the confidence.
ALWAYS_REQUIRES_APPROVAL = {
    "create_entity",
    "promote",
    "contradiction",
    "supersede",
    "merge",
    "split",
    "reclassify",
    "structural",
}

# Maps an approval-required operation to the specific KEP action label used
# downstream (a Proposal's `operation:` field, digest grouping).
OPERATION_TO_ACTION = {
    "create_entity": "propose",
    "promote": "promotion_candidate",
    "contradiction": "contradiction",
    "supersede": "supersede_candidate",
    "merge": "merge_candidate",
    "split": "merge_candidate",
    "reclassify": "propose",
    "structural": "propose",
}


@dataclass
class Decision:
    action: str          # one of claimstore.VALID_KEP_ACTIONS
    reason: str
    requires_approval: bool


def classify_claim(claim: dict) -> Decision:
    operation = claim["operation"]
    confidence = claim["confidence"]
    claim_type = claim["claim_type"]

    # Weak inference never becomes a proposal and never becomes fact. It's
    # logged as a signal; the same pattern showing up again in a later,
    # independent claim (operation=promote) is what earns it a real look.
    if operation == "weak_inference" or confidence == "low":
        return Decision(
            action="signal",
            reason="Weak inference or low confidence - logged as a Signal, not proposed.",
            requires_approval=False,
        )

    if operation in ALWAYS_REQUIRES_APPROVAL:
        action = OPERATION_TO_ACTION[operation]
        return Decision(
            action=action,
            reason=f"operation={operation!r} is always human-approval-required per KEP policy.",
            requires_approval=True,
        )

    if operation == "enrich_existing":
        # Only the narrow, explicitly-listed auto-apply shapes qualify.
        # Anything claiming to "enrich" but not high confidence still goes
        # to a human - ambiguous evidence must never auto-apply.
        if confidence == "high" and claim_type in {"observation", "fact", "relationship", "intention"}:
            return Decision(
                action="auto_apply",
                reason="Reversible, low-consequence, high-confidence update to an existing note.",
                requires_approval=False,
            )
        return Decision(
            action="propose",
            reason="enrich_existing but confidence is not high enough to auto-apply - evidence is ambiguous.",
            requires_approval=True,
        )

    # Anything that reaches here is an operation value not explicitly
    # reasoned about above. Fail safe: propose, never auto-apply an
    # unrecognised shape of change.
    return Decision(
        action="propose",
        reason=f"Unrecognised or unhandled operation={operation!r} - defaulting to human review.",
        requires_approval=True,
    )


if __name__ == "__main__":
    import json
    import sys

    claim = json.loads(sys.stdin.read())
    d = classify_claim(claim)
    print(json.dumps({"action": d.action, "reason": d.reason, "requires_approval": d.requires_approval}, indent=2))
