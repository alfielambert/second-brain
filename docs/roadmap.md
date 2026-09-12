# Roadmap

## Shipped in v0.2 (reliable unattended sync)

- Per-connector execution budgets (`resilience.run_step()`), independent
  of each other, instead of one global timeout - see docs/architecture.md.
- Safe retries: idempotent writes across the Claim Store, KEP routing,
  proposal creation, and applying claims, so a crash mid-run never
  duplicates or permanently skips work on the next attempt.
- The health-status/execution-status distinction, so "nothing new to
  ingest" can never be mistaken for "this connector is broken."
- A deterministic outbox (`outbox.py`) for proposal delivery, with a
  stdlib-only Telegram reference implementation - a retried sync can never
  re-send a proposal that already went out.
- An independent, read-only watchdog (`watchdog.py`) for connector
  staleness, meant to run as its own scheduled job.
- The Current + History + Sources pattern (`reports.py`) for recurring,
  scheduled evidence, with immutable per-run history snapshots.
- `second_brain.subprocess_timeout` for connectors that shell out to an
  external process, enforcing process-group-wide timeout termination.

## Shipped in v0.1

- Deterministic core: Claim Store, KEP, health/connector state, locking,
  safe note writes - zero dependency on any model provider.
- Two working connectors: `capture` (drop a file, get a weak claim) and
  `x_bookmarks` (real OAuth2 PKCE against the live X API).
- A CLI covering the full loop: `init`, `sync`, `route`, `approve`,
  `reject`, `status`, `compile`.
- A Claude Code-native runtime layer (`claude/`) for source interpretation,
  richer claim extraction, Daily Sync orchestration, and context synthesis.
- A fictional demo dataset exercising auto-apply, proposals, contradiction
  and supersession, and weak signals.

## Not yet built (known gaps, stated honestly)

- **Agent-agnostic runtime adapter.** The automated reasoning layer is
  Claude Code-native by design (see docs/architecture.md) - not because the
  deterministic core couldn't support another runtime, but because
  rewriting proven orchestration for hypothetical portability before anyone
  asked for it would be premature. The connector contract and KEP were kept
  free of Claude-specific assumptions specifically so this is buildable
  later without touching the Claim Store, KEP, or the knowledge model.
- **Telegram (or any) human-approval channel beyond the CLI.** `second-brain
  approve`/`reject` cover the governance mechanism; a chat-based approval
  flow (buttons, digests) is a real, useful pattern - it just isn't part of
  the portable core yet.
- **Gmail / Calendar / Notion connectors as real, runnable code.** These
  currently exist only as documented patterns (docs/connector-contract.md)
  because they depend on a user's own MCP grants - shipping fake code that
  only works with one person's account would be worse than not shipping it.
- **A "never delete/merge without approval" hard guard.** Today this is
  enforced by KEP's routing table (structurally, every relevant operation
  requires approval) plus the append-only Claim Store, but there's no
  independent code-level assertion blocking a bypass. Worth hardening.

## Contributions welcome on

Additional connectors following the documented contract (see
`second_brain/connectors/x_bookmarks.py` as the reference implementation),
and a first pass at the agent-agnostic runtime adapter.
