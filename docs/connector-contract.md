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

## Bounding a connector's execution time

A connector doesn't manage its own timeout - the caller does, via
`second_brain.resilience.run_step()`, which wraps the whole
discover→fetch→normalise→extract_claims→update_cursor cycle in one budget
(`connectors.<name>.session_timeout_seconds` in `second-brain.yml`,
per connector, not global) and returns a `ConnectorStepResult` rather than
raising. Write your connector's own functions as plain, synchronous calls
that just do their work - don't add your own timeout/retry logic inside
`discover()`/`fetch()`/etc., since `run_step()` already owns that
boundary and a second, overlapping timeout mechanism inside the connector
itself is more likely to produce confusing partial states than protect
anything.

If your connector legitimately detects its own failure (an expired token,
a malformed response it can't recover from), raise
`second_brain.resilience.ConnectorReportedError` with an explicit
`error_type` (`timeout` / `connection` / `auth` / `data` / `logic`) and a
`retryable: bool` - that's how the caller distinguishes "worth retrying
next run" from "needs a human to fix the auth grant first," rather than
guessing from an exception's class name.

If your connector shells out to an external process instead of calling a
library directly, use `second_brain.subprocess_timeout.run_with_timeout()`
rather than `subprocess.run(..., timeout=...)` directly - on timeout it
signals the whole process group, not just the immediate child, so a
subprocess's own children (a script your connector invokes that itself
spawns workers) can never be orphaned running past their budget. This
utility isn't used by either shipped connector today (both call libraries
directly, not subprocesses) - it exists for exactly this shape of
connector, documented here rather than left for every subprocess-based
connector to reinvent its own kill logic.

## Adapter patterns documented, not shipped

Gmail, Google Calendar, and Notion each have real, working access via
MCP-connected tools inside Claude Code, but that access is tied to your own
MCP configuration and account grants - it isn't portable code another user
could just run. Rather than ship something that only works with one
person's setup, the pattern for each is documented as prose in
`claude/README.md`: what claims to extract, what the stable source ID is,
and what confidence/operation to assign. Port them to real connectors as
your MCP setup allows.
