# Connector Contract

A connector's only job is turning a source into claims. It never decides
where a claim ends up - that's KEP's job. Six methods:

```python
discover(state) -> list[dict]        # raw source records not yet seen
fetch(item) -> dict                  # full content for one item
normalise(raw) -> dict               # -> {"source": {...}, "text": ...}
extract_claims(normalised) -> list[dict]  # -> kwargs for claimstore.append_claim()
update_cursor(vault_root, item)      # persist that this item is now seen
health(vault_root) -> dict           # a second_brain.health status block
```

This is deliberately not an enforced plugin framework - just six documented
functions. See `second_brain/connectors/__init__.py` for the full
docstring-as-contract, `second_brain/connectors/x_bookmarks.py` for a
complete real example, and `second_brain/connectors/capture.py` for the
simplest possible one.

## Idempotency

**Always key on a stable source ID, never on title/date matching.** A tweet
ID, a file path, a meeting UUID - something the source system itself
guarantees is stable and unique. Title/date matching breaks the moment two
sources produce similar-looking content, and it can't tell "already seen"
from "coincidentally similar." `x_bookmarks.py` demonstrates this concretely:
it stops paginating the instant it reaches a tweet ID it's already recorded
in `ClaimStore/state/x_bookmarks_seen.json`.

## Claim extraction without an LLM

Not every connector needs real judgement to be useful. Both shipped
connectors emit `claim_type=signal, operation=weak_inference,
confidence=low` for everything they see - "I observed this" rather than "this
is a fact." KEP always routes weak/low-confidence claims to a Signal, never
a proposal, so a connector like this can never spam you with approvals; it
just accumulates evidence that a real judgement call (yours, or the Claude
Code layer's) can later act on.

## Writing a connector with real extraction

If you want a connector that assigns richer claim types (a `decision`, a
`contradiction`, an `entity_update`), that's exactly the kind of judgement
call documented in `claude/README.md` - either write a Claude Code skill
that calls `extract_claims`-shaped output, or write your own deterministic
heuristic if the source is structured enough to not need one (e.g. a
calendar event's `attendees` field is already structured; you don't need an
LLM to turn that into a `relationship` claim).

## Adapter patterns documented, not shipped

Gmail, Google Calendar, and Notion each have real, working access via
MCP-connected tools inside Claude Code, but that access is tied to your own
MCP configuration and account grants - it isn't portable code another user
could just run. Rather than ship something that only works with one
person's setup, the pattern for each is documented as prose in
`claude/README.md`: what claims to extract, what the stable source ID is,
and what confidence/operation to assign. Port them to real connectors as
your MCP setup allows.
