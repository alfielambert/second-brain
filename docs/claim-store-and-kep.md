# Claim Store & KEP

## Claim Store

Two append-only JSONL streams, one file per UTC day:

- `ClaimStore/claims/YYYY-MM-DD.jsonl` - extracted claims, immutable
- `ClaimStore/events/YYYY-MM-DD.jsonl` - governance events (state transitions)

A claim's current status is never stored on the claim itself - it's derived
by replaying its events in order (`claimstore.current_status`). Nothing is
silently overwritten and nothing is ever deleted; retiring a wrong claim is
a `superseded` event, not a deletion. This is what makes the system
auditable: you can always answer "why does the vault currently say X" by
walking the event chain back to the original evidence.

Every write is a single atomic line append under an `flock`, so a sync run,
a CLI approval, and a watchdog process can never interleave or corrupt a
line - see `second_brain/claimstore.py`.

Schema: `second_brain/schema/claim.schema.json` and `event.schema.json`.

## KEP - Knowledge Evolution Protocol

KEP is deliberately **not** a model call. A connector's extraction step
(which may well use an LLM - see `claude/README.md`) decides *what* a claim
is: its `claim_type`, `operation`, `confidence`, and entities. KEP
(`second_brain/kep.py`) is a pure lookup table over
`(operation, confidence, claim_type)` that decides *where it goes*. Keeping
routing deterministic means it's testable, auditable, and never silently
drifts between runs.

| condition | action |
|---|---|
| `operation=weak_inference`, or any `confidence=low` | `signal` - logged, never proposed |
| `operation=enrich_existing`, `confidence=high`, `claim_type` in {observation, fact, relationship, intention} | `auto_apply` |
| `operation=enrich_existing`, confidence not high | `propose` |
| `operation` in {create_entity, promote, contradiction, supersede, merge, split, reclassify, structural} | always `propose` (specific action label varies) |
| anything else (unrecognised operation) | `propose` - fail-safe default |

**Only reversible, low-consequence, high-confidence updates to something
that already exists auto-apply.** Anything that creates a new entity,
changes a classification, or contradicts/supersedes existing knowledge
always goes to a human. This is a real, load-bearing design constraint, not
a suggestion - it's the whole reason a Second Brain built this way can be
trusted with automated ingestion in the first place.

## Governance events

`kep-decision -> proposal-created -> proposal-decision -> durable-write` is
the full chain for anything requiring approval; `kep-decision ->
auto-applied -> durable-write` for anything that doesn't. There is exactly
one governance path - not a faster/looser one depending on which channel
(CLI, Telegram, an agent) triggered the decision.

## Approving and rejecting

```
second-brain claims                     # see status of everything
second-brain route                      # run KEP over new claims
second-brain approve <claim_id>         # approve one proposal
second-brain approve --all-pending      # approve everything pending (fast for a demo; be more deliberate on a real vault)
second-brain reject <claim_id> --reason "..."
```

Approving a `supersede` claim automatically marks the prior durable claim
for the same `target_note` as superseded and records which claim superseded
it - see `second_brain/cli.py::_apply_claim`.
